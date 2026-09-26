"""Basic agent class. See https://mini-swe-agent.com/latest/advanced/control_flow/ for visual explanation
or https://minimal-agent.com for a tutorial on the basic building principles.
"""

import json
import logging
import os
import re
import traceback
from pathlib import Path

from jinja2 import StrictUndefined, Template
from pydantic import BaseModel

from minisweagent import Environment, Model, __version__
from minisweagent.exceptions import InterruptAgentFlow, LimitsExceeded
from minisweagent.skills.retrieval import retrieve_skill_content
from minisweagent.utils.serialize import recursive_merge

_DONE_PATTERN = re.compile(
    r"\b(done|finished|complete[ds]?|that'?s it|fix (is )?(applied|addresses|resolves|correct)|"
    r"no (more|further) changes|ready to submit|task is done|bug is fixed)\b",
    re.IGNORECASE,
)


class AgentConfig(BaseModel):
    """Check the config files in minisweagent/config for example settings."""

    system_template: str
    """Template for the system message (the first message)."""
    instance_template: str
    """Template for the first user message specifying the task (the second message overall)."""
    step_limit: int = 0
    """Maximum number of steps the agent can take."""
    cost_limit: float = 3.0
    """Stop agent after exceeding (!) this cost."""
    output_path: Path | None = None
    """Save the trajectory to this path."""


class DefaultAgent:
    def __init__(self, model: Model, env: Environment, *, config_class: type = AgentConfig, **kwargs):
        """See the `AgentConfig` class for permitted keyword arguments."""
        self.config = config_class(**kwargs)
        self.messages: list[dict] = []
        self.model = model
        self.env = env
        self.extra_template_vars = {}
        self.logger = logging.getLogger("agent")
        self.cost = 0.0
        self.n_calls = 0
        self._git_diff_step: int | None = None
        self._steps_since_diff = 0

    def get_template_vars(self, **kwargs) -> dict:
        return recursive_merge(
            self.config.model_dump(),
            self.env.get_template_vars(),
            self.model.get_template_vars(),
            {"n_model_calls": self.n_calls, "model_cost": self.cost},
            self.extra_template_vars,
            kwargs,
        )

    def _render_template(self, template: str) -> str:
        return Template(template, undefined=StrictUndefined).render(**self.get_template_vars())

    def _build_system_prompt(self) -> str:
        """Build system prompt."""
        return self._render_template(self.config.system_template)

    def _retrieve_skill(self, task: str) -> str:
        """Retrieve skill content based on MSWEA_RETRIEVAL_MODE environment variable.

        Modes:
          hierarchical (default) — Full 3-layer skill retrieval
          pr_rag                 — Retrieve similar PRs from JSONL dataset
          flat                   — Flat atomic skill retrieval from patch_pool
          hierarchical + MSWEA_LAYER_MODE — Layer-filtered retrieval
        """
        retrieval_mode = os.environ.get("MSWEA_RETRIEVAL_MODE", "hierarchical")
        layer_mode = os.environ.get("MSWEA_LAYER_MODE", "full")

        if retrieval_mode == "pr_rag":
            from minisweagent.skills.retrieval_pr_rag import retrieve_pr_content
            instance_id = os.environ.get("MSWEA_INSTANCE_ID", "")
            client = self._get_openai_client()
            model_name = self.model.config.model_name
            return retrieve_pr_content(task, client, model_name, instance_id=instance_id)

        elif retrieval_mode == "flat":
            from minisweagent.skills.retrieval_flat import retrieve_flat_skill
            client = self._get_openai_client()
            model_name = self.model.config.model_name
            return retrieve_flat_skill(task, client, model_name)

        elif layer_mode != "full":
            from minisweagent.skills.retrieval_layer_filter import retrieve_layer_filtered
            client = self._get_openai_client()
            model_name = self.model.config.model_name
            return retrieve_layer_filtered(task, client, model_name, layer_mode=layer_mode)

        else:
            # Default: full hierarchical skill retrieval
            return retrieve_skill_content(task, self.model)

    def _get_openai_client(self):
        """Get or create an OpenAI client for embedding/completion calls.

        If self.model already has a .client attribute (OpenAICustomModel), use it.
        Otherwise, create one from environment variables.
        """
        if hasattr(self.model, "client"):
            return self.model.client
        # Fallback: create a standalone OpenAI client
        from openai import OpenAI
        return OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )

    def _update_system_message(self):
        """Rebuild and replace messages[0] with current system prompt."""
        if self.messages:
            self.messages[0] = self.model.format_message(
                role="system", content=self._build_system_prompt()
            )

    def add_messages(self, *messages: dict) -> list[dict]:
        self.logger.debug(messages)  # set log level to debug to see
        self.messages.extend(messages)
        return list(messages)

    def handle_uncaught_exception(self, e: Exception) -> list[dict]:
        return self.add_messages(
            self.model.format_message(
                role="exit",
                content=str(e),
                extra={
                    "exit_status": type(e).__name__,
                    "submission": "",
                    "exception_str": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
        )

    def _has_done_signal(self) -> bool:
        """Check recent assistant messages and commands for 'done' patterns."""
        for msg in reversed(self.messages[-6:]):
            role = msg.get("role", "")
            if role == "assistant":
                content = msg.get("content") or ""
                if _DONE_PATTERN.search(content):
                    return True
                # Also check commands like echo "Done..."
                for action in msg.get("extra", {}).get("actions", []):
                    cmd = action.get("command", "")
                    if _DONE_PATTERN.search(cmd):
                        return True
        return False

    def _should_force_submit_reminder(self) -> bool:
        """Return True if we should inject a submit reminder.

        Triggers when git diff was detected AND either:
        - The model declared 'done' in a recent message/command, OR
        - 3 steps have passed since git diff without submitting.
        """
        if self._git_diff_step is None:
            return False
        self._steps_since_diff = self.n_calls - self._git_diff_step
        if self._has_done_signal():
            return True
        return self._steps_since_diff >= 3

    def run(self, task: str = "", **kwargs) -> dict:
        """Run step() until agent is finished. Returns dictionary with exit_status, submission keys."""
        self.extra_template_vars |= {"task": task, **kwargs}
        self.messages = []
        self._git_diff_step = None
        self._steps_since_diff = 0

        # Build initial messages: system + optional skill content + task
        system_msg = self.model.format_message(role="system", content=self._build_system_prompt())
        task_msg = self.model.format_message(role="user", content=self._render_template(self.config.instance_template))

        # Run skill retrieval sub-agent before the main task
        skill_content = self._retrieve_skill(task)
        if skill_content:
            skill_msg = self.model.format_message(role="user", content=skill_content)
            self.add_messages(system_msg, skill_msg, task_msg)
        else:
            self.add_messages(system_msg, task_msg)
        while True:
            try:
                self.step()
            except InterruptAgentFlow as e:
                self.add_messages(*e.messages)
            except Exception as e:
                self.handle_uncaught_exception(e)
                raise
            finally:
                self.save(self.config.output_path)
            if self.messages[-1].get("role") == "exit":
                break
            # Force-submit reminder: after git diff, if done signal or 3 steps without submit
            if self._should_force_submit_reminder():
                self.logger.info(
                    "Injecting submit reminder (git_diff_step=%s, steps_since=%s)",
                    self._git_diff_step, self._steps_since_diff,
                )
                self.add_messages(
                    self.model.format_message(
                        role="user",
                        content=(
                            "IMPORTANT: You have already run `git diff` and appear to be done with the fix. "
                            "You MUST submit your changes NOW. Follow these EXACT steps:\n\n"
                            "Step 1 — Create the patch (one command):\n"
                            '  bash tool: {"command": "git diff -- path/to/file1.py path/to/file2.py > patch.txt"}\n'
                            "  (Replace paths with the actual source files you modified.)\n\n"
                            "Step 2 — Submit the patch (separate command):\n"
                            '  bash tool: {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt"}\n\n'
                            "Do NOT run any other commands. Do NOT echo a summary. Submit NOW."
                        ),
                    )
                )
                self._git_diff_step = None  # reset to avoid repeated reminders
        return self.messages[-1].get("extra", {})

    def step(self) -> list[dict]:
        """Query the LM, execute actions."""
        self._update_system_message()
        return self.execute_actions(self.query())

    def query(self) -> dict:
        """Query the model and return model messages. Override to add hooks."""
        if 0 < self.config.step_limit <= self.n_calls or 0 < self.config.cost_limit <= self.cost:
            raise LimitsExceeded(
                {
                    "role": "exit",
                    "content": "LimitsExceeded",
                    "extra": {"exit_status": "LimitsExceeded", "submission": ""},
                }
            )
        self.n_calls += 1
        message = self.model.query(self.messages)
        self.cost += message.get("extra", {}).get("cost", 0.0)
        self.add_messages(message)
        return message

    def execute_actions(self, message: dict) -> list[dict]:
        """Execute actions in message, add observation messages."""
        actions = message.get("extra", {}).get("actions", [])
        outputs = []
        for action in actions:
            output = self.env.execute(action)
            outputs.append(output)
            # Track git diff execution
            command = action.get("command", "")
            if command and "git diff" in command and self._git_diff_step is None:
                self._git_diff_step = self.n_calls
                self._steps_since_diff = 0

        return self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))

    def serialize(self, *extra_dicts) -> dict:
        """Serialize agent state to a json-compatible nested dictionary for saving."""
        last_message = self.messages[-1] if self.messages else {}
        last_extra = last_message.get("extra", {})
        agent_data = {
            "info": {
                "model_stats": {
                    "instance_cost": self.cost,
                    "api_calls": self.n_calls,
                },
                "config": {
                    "agent": self.config.model_dump(mode="json"),
                    "agent_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                },
                "mini_version": __version__,
                "exit_status": last_extra.get("exit_status", ""),
                "submission": last_extra.get("submission", ""),
            },
            "messages": self.messages,
            "trajectory_format": "mini-swe-agent-1.1",
        }
        return recursive_merge(agent_data, self.model.serialize(), self.env.serialize(), *extra_dicts)

    def save(self, path: Path | None, *extra_dicts) -> dict:
        """Save the trajectory of the agent to a file if path is given. Returns full serialized data.
        You can pass additional dictionaries with extra data to be (recursively) merged into the output data.
        """
        data = self.serialize(*extra_dicts)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
        return data

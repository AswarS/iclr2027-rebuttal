"""Custom model using OpenAI SDK directly, bypassing litellm.

Use this when your API endpoint is OpenAI-compatible but litellm misroutes it.

Config example (in .env):
    OPENAI_API_KEY=sk-xxx
    OPENAI_API_BASE=https://your-api.com/v1

Usage:
    mini -m mco-4 --model-class openai_custom
    python run_local_swebench.py -d data.jsonl -m mco-4 --model-class openai_custom
"""

import json
import logging
import os
import time
from typing import Any

from openai import BadRequestError, OpenAI
from pydantic import BaseModel

from minisweagent.models import GLOBAL_MODEL_STATS
from minisweagent.models.utils.actions_toolcall import (
    BASH_TOOL,
    format_toolcall_observation_messages,
    parse_toolcall_actions,
)
from minisweagent.models.utils.openai_multimodal import expand_multimodal_content
from minisweagent.models.utils.retry import retry

logger = logging.getLogger("openai_custom_model")


class OpenAICustomModelConfig(BaseModel):
    model_name: str
    """Model name to pass to the API (e.g. 'mco-4')."""
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    """API key."""
    base_url: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    """API base URL."""
    model_kwargs: dict[str, Any] = {}
    """Additional arguments passed to the API (temperature, max_tokens, etc.)."""
    format_error_template: str = "{{ error }}"
    observation_template: str = (
        "{% if output.exception_info %}<exception>{{output.exception_info}}</exception>\n{% endif %}"
        "<returncode>{{output.returncode}}</returncode>\n<output>\n{{output.output}}</output>"
    )
    multimodal_regex: str = ""


class OpenAICustomModel:
    abort_exceptions: list[type[Exception]] = [KeyboardInterrupt, TypeError, ValueError, BadRequestError]

    def __init__(self, *, config_class=OpenAICustomModelConfig, **kwargs):
        self.config = config_class(**kwargs)
        self.client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=300.0,  # 5 minutes timeout for API calls
        )

    # litellm-specific kwargs that OpenAI SDK doesn't accept
    _LITELLM_ONLY_KWARGS = {"drop_params", "set_cache_control", "parallel_tool_calls"}

    def _query(self, messages: list[dict], **kwargs):
        merged = self.config.model_kwargs | kwargs
        # Strip litellm-specific params that OpenAI SDK doesn't understand
        cleaned = {k: v for k, v in merged.items() if k not in self._LITELLM_ONLY_KWARGS}
        params = {
            "model": self.config.model_name,
            "messages": messages,
            "tools": [BASH_TOOL],
            **cleaned,
        }
        logger.debug(f"Calling API with {len(messages)} messages, model={self.config.model_name}")
        try:
            response = self.client.chat.completions.create(**params)
            logger.debug(f"API call successful, received {len(response.choices)} choices")
            return response
        except BadRequestError:
            debug_path = "debug_messages.json"
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
            logger.error("BadRequestError! Cleaned messages dumped to %s (%d messages)", debug_path, len(messages))
            raise

    _CORE_MSG_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name"}
    _TOOL_CALL_KEYS = {"id", "type", "function"}
    _FUNCTION_KEYS = {"name", "arguments"}

    def _clean_tool_calls(self, tool_calls: list) -> list:
        """Strip tool_call dicts down to only id/type/function fields."""
        cleaned = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                ctc = {k: v for k, v in tc.items() if k in self._TOOL_CALL_KEYS}
                if "function" in ctc and isinstance(ctc["function"], dict):
                    ctc["function"] = {k: v for k, v in ctc["function"].items() if k in self._FUNCTION_KEYS}
                cleaned.append(ctc)
            else:
                cleaned.append(tc)
        return cleaned

    def _prepare_messages_for_api(self, messages: list[dict]) -> list[dict]:
        prepared = []
        for msg in messages:
            cleaned = {
                k: v for k, v in msg.items()
                if k in self._CORE_MSG_KEYS and v is not None
            }
            if "tool_calls" in cleaned:
                if not cleaned["tool_calls"]:
                    del cleaned["tool_calls"]
                else:
                    cleaned["tool_calls"] = self._clean_tool_calls(cleaned["tool_calls"])
                    # Proxies converting to Anthropic format reject assistant
                    # messages with empty content + tool_calls (creates an empty
                    # text block that Anthropic API refuses). Remove content when
                    # it's empty and tool_calls are present.
                    if not cleaned.get("content"):
                        cleaned.pop("content", None)
            elif "content" not in cleaned:
                cleaned["content"] = ""

            # Fix: Ensure assistant messages never have empty string content without tool_calls
            # Some API providers (especially Anthropic-compatible proxies) reject this
            if cleaned.get("role") == "assistant" and cleaned.get("content") == "" and "tool_calls" not in cleaned:
                cleaned.pop("content", None)

            # Handle remaining empty content by role:
            # - tool messages require content, use placeholder
            # - other roles: remove empty content entirely
            if cleaned.get("content") == "":
                if cleaned.get("role") == "tool":
                    cleaned["content"] = "(empty output)"
                else:
                    cleaned.pop("content", None)

            prepared.append(cleaned)
        return prepared

    def query(self, messages: list[dict], **kwargs) -> dict:
        for attempt in retry(logger=logger, abort_exceptions=self.abort_exceptions):
            with attempt:
                response = self._query(self._prepare_messages_for_api(messages), **kwargs)
        cost = self._estimate_cost(response)
        GLOBAL_MODEL_STATS.add(cost)
        message = response.choices[0].message.model_dump()
        message["extra"] = {
            "actions": self._parse_actions(response),
            "response": response.model_dump(),
            "cost": cost,
            "timestamp": time.time(),
        }
        return message

    def _estimate_cost(self, response) -> float:
        """Estimate cost from token usage. Returns 0 if unavailable."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0.0
        # Generic estimate: $0.01/1K input, $0.03/1K output (override if needed)
        input_cost = (usage.prompt_tokens or 0) / 1000 * 0.01
        output_cost = (usage.completion_tokens or 0) / 1000 * 0.03
        return input_cost + output_cost

    def _parse_actions(self, response) -> list[dict]:
        tool_calls = response.choices[0].message.tool_calls or []
        return parse_toolcall_actions(tool_calls, format_error_template=self.config.format_error_template)

    def format_message(self, **kwargs) -> dict:
        return expand_multimodal_content(kwargs, pattern=self.config.multimodal_regex)

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        return format_toolcall_observation_messages(
            actions=actions,
            outputs=outputs,
            observation_template=self.config.observation_template,
            template_vars=template_vars,
            multimodal_regex=self.config.multimodal_regex,
        )

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return self.config.model_dump()

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "model": self.config.model_dump(mode="json"),
                    "model_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                },
            }
        }

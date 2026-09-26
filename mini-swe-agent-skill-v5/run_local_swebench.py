#!/usr/bin/env python3
"""Run mini-swe-agent on SWE-bench instances from a local JSONL file using Docker.

Each instance runs inside its pre-built SWE-bench Docker image.
Images must be available locally with the naming convention:
    ghcr.io/epoch-research/swe-bench.eval.x86_64.<instance_id>

Usage:
    python run_local_swebench.py -d swe-bench-lite_test.jsonl -n 1
    python run_local_swebench.py -d swe-bench-lite_test.jsonl -n 5
    python run_local_swebench.py -d swe-bench-lite_test.jsonl -i astropy__astropy-12907
"""

import json
import logging
import os
import re
import time
import traceback
from pathlib import Path

import typer
from rich.console import Console

from minisweagent.agents.default import DefaultAgent
from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.environments import get_environment
from minisweagent.models import get_model
from minisweagent.models.utils.content_string import get_content_string
from minisweagent.utils.serialize import recursive_merge

app = typer.Typer(rich_markup_mode="rich", add_completion=False)
console = Console(highlight=False)

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG_FILE = builtin_config_dir / "benchmarks" / "swebench.yaml"

IMAGE_PREFIX = os.getenv(
    "MSWEA_DOCKER_IMAGE_PREFIX",
    "ghcr.io/epoch-research/swe-bench.eval.x86_64.",
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_instances_from_jsonl(path: Path) -> list[dict]:
    instances = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    return instances


def get_docker_image_name(instance_id: str, data_file: str = "") -> str:
    """Build the Docker image name for a given SWE-bench instance."""
    if Path(data_file).stem == "swe-bench-multilingual":
        repo, issue = instance_id.split("__", 1)
        return f"swebench/sweb.eval.x86_64.{repo}_1776_{issue}:v1"
    return f"{IMAGE_PREFIX}{instance_id}"


# ── Custom agent with idle-command detection ─────────────────────────────────

_IDLE_COMMAND_PATTERN = re.compile(
    r"^\s*(?:true|echo\s+[\"']?(?:ready|Awaiting next instruction|ok|Task complete|Done)[\"']?)\s*$",
    re.IGNORECASE,
)

SUBMIT_COMMAND = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


class ForceSubmitAgent(DefaultAgent):
    """Agent that forces submission when the model outputs idle/no-op commands."""

    def __init__(self, *args, verbose: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.verbose = verbose

    def add_messages(self, *messages: dict) -> list[dict]:
        """Override to print messages when verbose mode is enabled."""
        if self.verbose:
            for msg in messages:
                role = msg.get("role", "unknown")
                content = get_content_string(msg)
                if role == "assistant":
                    console.print(f"\n[red][bold]Agent[/bold] (step {self.n_calls}, ${self.cost:.2f}):[/red]")
                    console.print(content, highlight=False, markup=False)
                elif role == "tool":
                    console.print(f"\n[bold green]Tool result:[/bold green]")
                    console.print(content, highlight=False, markup=False)
                elif role == "user":
                    console.print(f"\n[bold blue]User:[/bold blue]")
                    console.print(content, highlight=False, markup=False)
        return super().add_messages(*messages)

    def execute_actions(self, message: dict) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        for action in actions:
            command = action.get("command", "")
            if command and _IDLE_COMMAND_PATTERN.match(command):
                self.logger.info(f"Idle command detected: {command!r}, forcing submit")
                action["command"] = SUBMIT_COMMAND
        return super().execute_actions(message)


# ── Instance processing ──────────────────────────────────────────────────────

def process_instance(
    instance: dict,
    output_dir: Path,
    config: dict,
    verbose: bool = False,
    data_file: str = "",
) -> dict:
    """Process a single instance inside its Docker container."""
    instance_id = instance["instance_id"]
    task = instance["problem_statement"]
    instance_dir = output_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)

    # Set instance_id env var for PR-RAG self-exclusion
    os.environ["MSWEA_INSTANCE_ID"] = instance_id

    image_name = get_docker_image_name(instance_id, data_file)
    console.print(f"  [docker] Using image: {image_name}")

    instance_config = recursive_merge(config, {
        "environment": {
            "environment_class": "docker",
            "image": image_name,
            "cwd": "/testbed",
            "timeout": 300,
            "interpreter": ["bash", "-c"],
        },
    })

    model = get_model(config=instance_config.get("model", {}))
    env = get_environment(instance_config.get("environment", {}))

    agent_config = instance_config.get("agent", {})
    agent_config.pop("agent_class", None)
    agent = ForceSubmitAgent(model, env, verbose=verbose, **agent_config)

    exit_status = None
    result = None
    extra_info = {}

    try:
        info = agent.run(task)
        exit_status = info.get("exit_status")
        result = info.get("submission", "")
    except Exception as e:
        logging.error(f"Error processing {instance_id}: {e}", exc_info=True)
        exit_status = type(e).__name__
        result = ""
        extra_info = {"traceback": traceback.format_exc(), "exception_str": str(e)}
    finally:
        traj_path = instance_dir / f"{instance_id}.traj.json"
        agent.save(
            traj_path,
            {
                "info": {"exit_status": exit_status, "submission": result, **extra_info},
                "instance_id": instance_id,
            },
        )
        preds_path = output_dir / "preds.json"
        preds = {}
        if preds_path.exists():
            preds = json.loads(preds_path.read_text(encoding="utf-8"))
        preds[instance_id] = {
            "model_name_or_path": model.config.model_name,
            "instance_id": instance_id,
            "model_patch": result,
        }
        preds_path.write_text(json.dumps(preds, indent=2), encoding="utf-8")

        if hasattr(env, "cleanup"):
            env.cleanup()

    return {"instance_id": instance_id, "exit_status": exit_status}


# ── Main ─────────────────────────────────────────────────────────────────────

@app.command()
def main(
    data: Path = typer.Option(..., "--data", "-d", help="Path to SWE-bench JSONL file"),
    num: int = typer.Option(0, "--num", "-n", help="Number of instances to run (0=all)"),
    instance_filter: str = typer.Option("", "--instance", "-i", help="Run only this instance ID"),
    output: str = typer.Option("output_swebench", "-o", "--output", help="Output directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed agent logs in console"),
) -> None:
    """Run mini-swe-agent on SWE-bench instances using Docker containers."""
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    # Load instances
    console.print(f"Loading instances from [bold green]{data}[/bold green]")
    instances = load_instances_from_jsonl(data)
    console.print(f"Loaded [bold]{len(instances)}[/bold] instances total")

    # Filter by instance ID if specified
    if instance_filter:
        instances = [inst for inst in instances if inst["instance_id"] == instance_filter]
        if not instances:
            console.print(f"[bold red]Instance {instance_filter} not found in dataset.[/bold red]")
            raise typer.Exit(1)

    # Skip already completed
    preds_path = output_path / "preds.json"
    if preds_path.exists():
        existing = set(json.loads(preds_path.read_text(encoding="utf-8")).keys())
        before = len(instances)
        instances = [inst for inst in instances if inst["instance_id"] not in existing]
        if before != len(instances):
            console.print(f"Skipping [bold]{before - len(instances)}[/bold] already completed")

    # Limit to num (0 = all)
    if num > 0:
        instances = instances[:num]
    console.print(f"Running [bold green]{len(instances)}[/bold green] instances")

    if not instances:
        console.print("[yellow]No instances to run.[/yellow]")
        return

    # Read model config from env
    model_name = os.environ.get("MSWEA_MODEL_NAME", "mco-4")
    if "/" in model_name:
        model_name = model_name.split("/", 1)[1]

    config = recursive_merge(
        get_config_from_spec(str(DEFAULT_CONFIG_FILE)),
        {
            "agent": {
                "mode": "yolo",
                "confirm_exit": False,
                "cost_limit": 0,
            },
            "model": {
                "model_name": model_name,
                "model_class": "openai_custom",
            },
            "environment": {
                "environment_class": "docker",
            },
        },
    )

    results = []
    for idx, instance in enumerate(instances):
        iid = instance["instance_id"]

        console.print(f"\n{'='*60}")
        console.print(f"[bold][{idx+1}/{len(instances)}] {iid}[/bold]")
        console.print(f"  repo: {instance['repo']}  commit: {instance['base_commit'][:8]}")
        console.print(f"{'='*60}")

        t0 = time.time()
        result = process_instance(instance, output_path, config, verbose=verbose, data_file=str(data))
        elapsed = time.time() - t0

        results.append(result)
        status = result["exit_status"]
        color = "green" if status == "Submitted" else "red"
        console.print(f"[{color}]{iid}: {status}[/{color}] ({elapsed:.1f}s)")

    # Summary
    console.print(f"\n{'='*60}")
    submitted = sum(1 for r in results if r["exit_status"] == "Submitted")
    console.print(f"[bold]Done:[/bold] {submitted}/{len(results)} submitted, output: {output_path}")


if __name__ == "__main__":
    app()

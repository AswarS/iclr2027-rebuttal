"""Parse SWE-bench parquet/jsonl data into structured PR information."""

import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path

import pandas as pd


# =============================================================================
# Raw SWE-bench data
# =============================================================================

@dataclass
class PRData:
    """Structured representation of a PR from SWE-bench."""
    instance_id: str
    repo: str
    problem_statement: str
    patch: str
    test_patch: str
    hints_text: str
    changed_files: List[str] = field(default_factory=list)
    change_summary: str = ""


# =============================================================================
# Normalized PR Instance (design spec §3.1)
# =============================================================================

@dataclass
class Change:
    """DEPRECATED: A single file-level code change. Kept for backward compat with old examples."""
    type: str  # "add" | "modify" | "remove"
    target: str  # file or component affected
    description: str


@dataclass
class Action:
    """A semantic action — one logical behavior unit extracted from a PR."""
    action: str           # imperative verb phrase: "Add --quiet CLI flag"
    description: str      # what this action accomplishes (1-2 sentences)
    type: str             # "add" | "modify" | "remove" | "refactor" | "fix"
    target: str           # logical target: "CLI argument parser", not "commands.py"
    files: List[str] = field(default_factory=list)  # files involved (traceability)
    contribution: str = ""  # how this action serves the overall PR intent
    importance: str = "core"  # "core" | "supporting" | "cleanup"
    per_file_rationale: Dict[str, str] = field(default_factory=dict)  # file → why this file was changed


@dataclass
class ActionDependency:
    """Ordering relationship between actions."""
    from_action: int      # index of prerequisite action
    to_action: int        # index of dependent action
    reason: str = ""      # why this ordering matters


@dataclass
class DecisionPoint:
    """An explicit design decision made in the PR."""
    problem: str
    decision: str
    rationale: str


@dataclass
class Outcome:
    """Summary of PR outcome."""
    summary: str


@dataclass
class PRInstance:
    """Normalized PR instance — produced by LLM parsing of PRData."""
    instance_id: str
    repo: str
    intent: str
    actions: List[Action] = field(default_factory=list)
    action_dependencies: List[ActionDependency] = field(default_factory=list)
    decision_points: List[DecisionPoint] = field(default_factory=list)
    outcome: Outcome = field(default_factory=lambda: Outcome(summary=""))
    # Deep abstraction fields
    root_cause: str = ""              # Essential problem at the design-principle level (no project specifics)
    cognitive_error: str = ""         # The developer mental-model failure that led to the bug
    other_manifestations: List[str] = field(default_factory=list)  # Other forms the same root cause can take

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "intent": self.intent,
            "actions": [
                {
                    "action": a.action,
                    "description": a.description,
                    "type": a.type,
                    "target": a.target,
                    "files": a.files,
                    "contribution": a.contribution,
                    "importance": a.importance,
                    "per_file_rationale": a.per_file_rationale,
                }
                for a in self.actions
            ],
            "action_dependencies": [
                {"from_action": d.from_action, "to_action": d.to_action, "reason": d.reason}
                for d in self.action_dependencies
            ],
            "decision_points": [
                {"problem": d.problem, "decision": d.decision, "rationale": d.rationale}
                for d in self.decision_points
            ],
            "outcome": {"summary": self.outcome.summary},
            "root_cause": self.root_cause,
            "cognitive_error": self.cognitive_error,
            "other_manifestations": self.other_manifestations,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "PRInstance":
        return PRInstance(
            instance_id=data.get("instance_id", ""),
            repo=data.get("repo", ""),
            intent=data.get("intent", ""),
            actions=[Action(**{**a, "per_file_rationale": a.get("per_file_rationale", {})}) for a in data.get("actions", [])],
            action_dependencies=[ActionDependency(**d) for d in data.get("action_dependencies", [])],
            decision_points=[DecisionPoint(**d) for d in data.get("decision_points", [])],
            outcome=Outcome(**data.get("outcome", {"summary": ""})),
            root_cause=data.get("root_cause", ""),
            cognitive_error=data.get("cognitive_error", ""),
            other_manifestations=data.get("other_manifestations", []),
        )


def parse_patch(patch: str) -> Dict[str, Any]:
    """Parse a unified diff patch into structured information.

    Returns:
        {
            "files": [{"path": str, "additions": int, "deletions": int, "hunks": [str]}],
            "total_additions": int,
            "total_deletions": int,
        }
    """
    files = []
    current_file = None
    current_hunk_lines = []

    for line in patch.split("\n"):
        if line.startswith("diff --git"):
            # Save previous file
            if current_file and current_hunk_lines:
                current_file["hunks"].append("\n".join(current_hunk_lines))
            # Start new file
            match = re.search(r'diff --git a/(.+?) b/', line)
            file_path = match.group(1) if match else "unknown"
            current_file = {
                "path": file_path,
                "additions": 0,
                "deletions": 0,
                "hunks": [],
            }
            files.append(current_file)
            current_hunk_lines = []
        elif line.startswith("@@") and current_file is not None:
            if current_hunk_lines:
                current_file["hunks"].append("\n".join(current_hunk_lines))
            current_hunk_lines = [line]
        elif current_file is not None:
            current_hunk_lines.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                current_file["additions"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                current_file["deletions"] += 1

    # Save last file
    if current_file and current_hunk_lines:
        current_file["hunks"].append("\n".join(current_hunk_lines))

    total_add = sum(f["additions"] for f in files)
    total_del = sum(f["deletions"] for f in files)

    return {
        "files": files,
        "total_additions": total_add,
        "total_deletions": total_del,
    }


def format_patch_summary(patch: str) -> str:
    """Create a human-readable summary of a patch."""
    info = parse_patch(patch)
    lines = [f"Total: +{info['total_additions']} -{info['total_deletions']} across {len(info['files'])} file(s)"]
    for f in info["files"]:
        lines.append(f"  {f['path']}: +{f['additions']} -{f['deletions']}")
    return "\n".join(lines)


MAX_PATCH_CHARS = 500_000  # Skip PRs with patches larger than this to avoid memory issues


def load_dataset(dataset_path: str) -> List[PRData]:
    """Load dataset and return list of PRData. Supports parquet and jsonl."""
    path = Path(dataset_path)
    if path.suffix == ".jsonl":
        return _load_jsonl(str(path))
    return _load_parquet(str(path))


def _load_jsonl(dataset_path: str) -> List[PRData]:
    """Load jsonl dataset (one JSON object per line, same fields as SWE-bench)."""
    results = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            patch = row.get("patch", "") or ""
            if len(patch) > MAX_PATCH_CHARS:
                continue
            patch_info = parse_patch(patch)
            changed_files = [f["path"] for f in patch_info["files"]]
            change_summary = format_patch_summary(patch)

            results.append(PRData(
                instance_id=row["instance_id"],
                repo=row["repo"],
                problem_statement=row["problem_statement"],
                patch=patch,
                test_patch=row.get("test_patch", ""),
                hints_text=row.get("hints_text", ""),
                changed_files=changed_files,
                change_summary=change_summary,
            ))
    return results


def _load_parquet(dataset_path: str) -> List[PRData]:
    """Load SWE-bench parquet dataset and return list of PRData."""
    path = Path(dataset_path)
    df = pd.read_parquet(str(path))

    results = []
    for _, row in df.iterrows():
        patch = row.get("patch", "") or ""
        if len(patch) > MAX_PATCH_CHARS:
            continue
        patch_info = parse_patch(patch)
        changed_files = [f["path"] for f in patch_info["files"]]
        change_summary = format_patch_summary(patch)

        results.append(PRData(
            instance_id=row["instance_id"],
            repo=row["repo"],
            problem_statement=row["problem_statement"],
            patch=patch,
            test_patch=row.get("test_patch", ""),
            hints_text=row.get("hints_text", ""),
            changed_files=changed_files,
            change_summary=change_summary,
        ))

    return results

"""Stage 1: PR 语义解构 (Extract & Decompose).

从 PR 原始数据中提取结构化 PRInstance，并拆分为独立的 Dimensions。
每个 Dimension 具有不同的 Root Cause，可独立触发且在不同场景下复用。
"""

import json
import re
from typing import Dict, Any, List, Tuple

from ..llm import LLMClient
from ..pr_parser import (
    PRData, PRInstance, Action, ActionDependency, DecisionPoint, Outcome,
)


# =============================================================================
# Prompts
# =============================================================================

PARSE_PR_PROMPT = """You are an expert code reviewer and software design analyst. Analyze the following Pull Request and extract a structured instance at the SEMANTIC level (behavior units), NOT at the file level. Beyond the surface-level changes, you must reason deeply about the UNDERLYING DESIGN PROBLEM and the COGNITIVE ERROR that caused it.

## Repository: {repo}

## Issue Description
{problem_statement}

## Code Changes (unified diff)
{patch}

## Changed Files Summary
{change_summary}

---

Your task has TWO parts:

### Part 1: Decompose into semantic actions
Decompose this PR into **semantic actions** — logical behavior units that each accomplish one coherent goal. A single action may span multiple files, and a single file may contain parts of multiple actions. Do NOT map one action per file.

### Part 2: Deep abstraction — extract the essential problem
Go beyond WHAT was changed to understand WHY it was wrong and WHAT THINKING LED TO THE BUG.

Perform 3 levels of "why" abstraction for root_cause:
  Level 0 (FORBIDDEN — too concrete): "Function X used value Y instead of Z"
  Level 1 (FORBIDDEN — still implementation-bound): "The right branch used a hardcoded default"
  Level 2 (BORDERLINE — still tied to one form): "Symmetric binary operations had asymmetric handling"
  Level 3 (CORRECT — essential problem): "Code branches that should apply equivalent processing to equivalent inputs used a simplified assumption for some branches, which fails when input complexity exceeds the assumption"

Respond in EXACTLY this JSON format (no other text):

```json
{{
  "intent": "<1-2 sentences: what problem does this PR solve, stated as a trigger condition>",
  "actions": [
    {{
      "action": "<imperative verb phrase: what to do, e.g. 'Add --quiet flag to CLI argument parser'>",
      "description": "<1-2 sentences: what this action accomplishes>",
      "type": "add|modify|remove|refactor|fix",
      "target": "<logical component/subsystem affected, NOT a filename>",
      "files": ["<file1>", "<file2>"],
      "contribution": "<how this action serves the overall PR intent>",
      "importance": "core|supporting|cleanup",
      "per_file_rationale": {{
        "<file1>": "<why this specific file was changed for this action>",
        "<file2>": "<why this specific file was changed for this action>"
      }}
    }}
  ],
  "action_dependencies": [
    {{
      "from_action": 0,
      "to_action": 1,
      "reason": "<why action 0 must happen before action 1>"
    }}
  ],
  "decision_points": [
    {{
      "problem": "<what design problem was faced>",
      "decision": "<what choice was made>",
      "rationale": "<why this choice>"
    }}
  ],
  "outcome": {{
    "summary": "<1-2 sentences: result of the PR>"
  }},
  "root_cause": "<The essential design-level problem, free of ANY project names, file names, function names, class names, or data structure names. State it as a universal software engineering principle violation.>",
  "cognitive_error": "<What implicit assumption did the developer hold when writing the original buggy code? What was wrong with their mental model? Do NOT describe the bug — describe the THINKING that produced the bug.>",
  "other_manifestations": [
    "<A completely different scenario (different domain, different data structure, different symptom) where the SAME root cause and cognitive error would produce a bug>",
    "<Another genuinely different scenario>"
  ]
}}
```

IMPORTANT:
- Group changes by LOGICAL BEHAVIOR, not by file. One action = one coherent behavioral change.
- "action" must be an imperative verb phrase describing WHAT SHOULD BE DONE (not what was changed).
- "target" must be a logical component (e.g. "CLI argument parser", "output formatter", "test suite"), NOT a file path.
- "contribution" explains WHY this action matters to the overall PR goal.
- "importance": "core" = essential to the PR intent, "supporting" = enables or complements core actions, "cleanup" = cosmetic or incidental.
- "per_file_rationale" must cover every file in "files" — explain the specific role each file plays in this action.
- "action_dependencies" captures execution ordering — which actions must happen before others.
- decision_points MUST be explicitly inferred — at least 1 decision point.
- Keep descriptions concise but informative.

DEEP ABSTRACTION REQUIREMENTS:
- "root_cause" must contain ZERO project-specific nouns. Test: could someone from a completely different tech stack read it and understand the problem? If not, abstract further.
- "cognitive_error" must describe the DEVELOPER'S MENTAL MODEL failure, not the code defect. Ask: "What did the developer believe about the inputs/state that turned out to be wrong?"
- "other_manifestations" must list 2-3 genuinely DIFFERENT scenarios (different domain, different data structure, different symptom) that share the same root cause. They should NOT be minor variations of the current bug."""


DECOMPOSE_PR_PROMPT = """You are analyzing a PR to determine whether it contains multiple independent, reusable pieces of DESIGN KNOWLEDGE (thinking patterns), not just multiple code changes.

## PR Intent
{intent}

## Root Cause
{root_cause}

## Cognitive Error
{cognitive_error}

## Semantic Actions
{actions_text}

## Decision Points
{decisions_text}

---

Your task: decide whether this PR should produce ONE skill or MULTIPLE skills.

A skill captures a THINKING PATTERN — a reusable piece of design reasoning. Split into multiple skills ONLY when the PR addresses genuinely DIFFERENT cognitive problems:

Split ONLY when ALL of the following are true for each candidate skill:
1. **Different root cause**: Each skill addresses a fundamentally different design principle or cognitive error.
2. **Independently triggerable**: A developer could encounter one thinking problem without the other.
3. **Independently reusable**: The reasoning pattern of one skill is useful without the other.

Do NOT split when:
- The actions address different SYMPTOMS of the SAME root cause (same thinking error, different manifestations)
- One part is purely a side-effect of the other (e.g. "add feature" + "add tests for that feature")
- The parts are always logically paired in practice
- Splitting would leave one skill without a coherent standalone thinking pattern
- The only distinguishing actions are `cleanup` importance (tests, docs, formatting) — these should be absorbed into the skill they support

For each resulting skill (1 or more), assign the relevant action indices from the list above.

Reply in EXACTLY this JSON format (no other text):

```json
{{
  "skills": [
    {{
      "label": "<short label for this skill dimension, e.g. 'equivalence-assumption'>",
      "action_indices": [0, 1],
      "root_cause": "<root cause specific to this dimension>"
    }}
  ],
  "rationale": "<1-2 sentences: why you split or kept as one>"
}}
```

If keeping as one skill, return a single entry in "skills" with all action indices."""


# =============================================================================
# Stage 1 Implementation
# =============================================================================

class DecomposeStage:
    """Stage 1: Parse PR into PRInstance and split into Dimensions."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def run(self, pr: PRData) -> Tuple[PRInstance, List[Dict[str, Any]]]:
        """Execute Stage 1: parse PR and decompose into dimensions.

        Returns:
            (PRInstance, list of dimension dicts with keys: label, action_indices, root_cause)
        """
        instance = await self._parse_pr(pr)
        dimensions = await self._decompose(instance)
        return instance, dimensions

    async def _parse_pr(self, pr: PRData) -> PRInstance:
        """Parse a PRData into a normalized PRInstance via LLM."""
        patch = pr.patch
        if len(patch) > 15000:
            patch = patch[:15000] + "\n... (truncated)"

        prompt = PARSE_PR_PROMPT.format(
            repo=pr.repo,
            problem_statement=pr.problem_statement,
            patch=patch,
            change_summary=pr.change_summary,
        )

        response = await self.llm.chat([
            {"role": "system", "content": "You are an expert code reviewer and software design analyst. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ])

        parsed = _extract_json(response)

        actions = []
        for a in parsed.get("actions", []):
            actions.append(Action(
                action=a.get("action", ""),
                description=a.get("description", ""),
                type=a.get("type", "modify"),
                target=a.get("target", ""),
                files=a.get("files", []),
                contribution=a.get("contribution", ""),
                importance=a.get("importance", "core"),
                per_file_rationale=a.get("per_file_rationale", {}),
            ))

        deps = []
        for d in parsed.get("action_dependencies", []):
            deps.append(ActionDependency(
                from_action=d.get("from_action", 0),
                to_action=d.get("to_action", 0),
                reason=d.get("reason", ""),
            ))

        decision_points = []
        for d in parsed.get("decision_points", []):
            decision_points.append(DecisionPoint(
                problem=d.get("problem", ""),
                decision=d.get("decision", ""),
                rationale=d.get("rationale", ""),
            ))

        outcome_data = parsed.get("outcome", {})
        outcome = Outcome(summary=outcome_data.get("summary", ""))

        return PRInstance(
            instance_id=pr.instance_id,
            repo=pr.repo,
            intent=parsed.get("intent", ""),
            actions=actions,
            action_dependencies=deps,
            decision_points=decision_points,
            outcome=outcome,
            root_cause=parsed.get("root_cause", ""),
            cognitive_error=parsed.get("cognitive_error", ""),
            other_manifestations=parsed.get("other_manifestations", []),
        )

    async def _decompose(self, instance: PRInstance) -> List[Dict[str, Any]]:
        """Decompose PRInstance into skill dimensions."""
        actions_text = _format_actions(instance)
        decisions_text = _format_decisions(instance)

        prompt = DECOMPOSE_PR_PROMPT.format(
            intent=instance.intent,
            root_cause=instance.root_cause or "(not identified)",
            cognitive_error=instance.cognitive_error or "(not identified)",
            actions_text=actions_text,
            decisions_text=decisions_text,
        )

        response = await self.llm.chat([
            {"role": "system", "content": "You are a precise skill decomposer. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ])

        parsed = _extract_json(response)
        dimensions = parsed.get("skills", [])

        if not dimensions:
            dimensions = [{
                "label": "main",
                "action_indices": list(range(len(instance.actions))),
                "root_cause": instance.root_cause or "",
            }]

        return dimensions


# =============================================================================
# Shared helpers
# =============================================================================

def _extract_json(response: str) -> Dict[str, Any]:
    """Extract JSON from LLM response (may be wrapped in ```json blocks)."""
    match = re.search(r'```json\s*\n(.*?)\n\s*```', response, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        text = response.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass
        return {"intent": response[:200], "actions": [], "action_dependencies": [],
                "decision_points": [], "outcome": {"summary": ""}}


def _format_actions(instance: PRInstance) -> str:
    """Format semantic actions for prompt input, ordered by importance."""
    if not instance.actions:
        return "  (none)"
    order = {"core": 0, "supporting": 1, "cleanup": 2}
    sorted_actions = sorted(
        enumerate(instance.actions),
        key=lambda x: order.get(x[1].importance, 1),
    )
    lines = []
    for idx, a in sorted_actions:
        entry = (
            f"  [{idx}] ({a.importance}) [{a.type}] {a.action}\n"
            f"      Target: {a.target}\n"
            f"      Description: {a.description}\n"
            f"      Contribution: {a.contribution}\n"
            f"      Files: {', '.join(a.files)}"
        )
        if a.per_file_rationale:
            rationale_lines = "\n".join(
                f"        {f}: {r}" for f, r in a.per_file_rationale.items()
            )
            entry += f"\n      Per-file rationale:\n{rationale_lines}"
        lines.append(entry)
    return "\n".join(lines)


def _format_dependencies(instance: PRInstance) -> str:
    """Format action dependencies for prompt input."""
    if not instance.action_dependencies:
        return "  (none)"
    return "\n".join(
        f"  Action [{d.from_action}] → Action [{d.to_action}]: {d.reason}"
        for d in instance.action_dependencies
    )


def _format_decisions(instance: PRInstance) -> str:
    """Format decision points for prompt input."""
    if not instance.decision_points:
        return "  (none)"
    return "\n".join(
        f"  - Problem: {d.problem}\n    Decision: {d.decision}\n    Rationale: {d.rationale}"
        for d in instance.decision_points
    )

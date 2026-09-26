"""Stage 2: 原子技能补丁化 (Skill Patch Generation).

将每个 Dimension 转化为标准化的 SkillPatch，包含：
- 4D-Tags (Domain, Failure Signal, Problem Pattern, Artifact)
- Pattern Recognition / Root Cause / Solution Strategy 结构
- LLM 验证：生成解决思路与 ground truth patch 对比
"""

import json
import re
from typing import Dict, Any, List, Optional

from ..llm import LLMClient, LocalEmbedder
from ..pr_parser import PRData, PRInstance
from ..taxonomy import Taxonomy, DIMENSIONS
from . import SkillPatch


# =============================================================================
# Prompts
# =============================================================================

GENERATE_PATCH_PROMPT = """You are converting a PR dimension into an atomic skill patch — a reusable piece of design knowledge that serves as aggregation material for higher-level patterns.

## PR Context
- Instance ID: {instance_id}
- Repo: {repo}
- Intent: {intent}
- Problem Statement (excerpt): {problem_excerpt}

## Root Cause
{root_cause}

## Cognitive Error
{cognitive_error}

## Semantic Actions for this Dimension
{actions_text}

## Decision Points
{decisions_text}

## Tag Dimensions and Allowed Values

### 1. Problem Category (structural bug class) — select 1-2
Describes the structural cause of the bug, not the tech stack.
Examples: "data-modification", "state-synchronization", "resource-lifecycle", "boundary-handling", "control-flow", "concurrency", "type-coercion"
Allowed: {domain_tags}
If no allowed tag fits, prefix with [CANDIDATE] and create a new one (kebab-case).

### 2. Problem Pattern (root cause logic) — select 1-2
Allowed: {problem_pattern_tags}
If no allowed tag fits, prefix with [CANDIDATE].

---

Generate a skill patch. This patch is an ATOMIC skill — a mini-skill that captures one specific piece of design knowledge. It will later be aggregated with similar patches to form higher-level patterns.

Reply in EXACTLY this JSON format (no other text):

```json
{{
  "tags": {{
    "domain": ["<tag>"],
    "problem_pattern": ["<tag>"]
  }},
  "confidence_score": 0.0,
  "content": "<markdown content, see format below>"
}}
```

### Content Format:
The "content" field must be a markdown string with these sections:

## Pattern Recognition
<1-3 sentences: what observable signals indicate this problem? How would an agent recognize it is facing this specific issue?>

## Root Cause
<1-3 sentences: the underlying structural/cognitive reason this bug occurs. What is the fundamental misunderstanding or oversight?>

## Solution Strategy
<2-4 imperative sentences: concrete steps to resolve this class of problem. Direct instructions an AI agent can follow.>

IMPORTANT:
- Content must contain ZERO project-specific nouns (no file names, class names, function names from the PR).
- State the pattern generically so it can apply to any similar situation.
- Tags: use allowed values when they fit. For new tags, prefix with [CANDIDATE].
- confidence_score: 0.0-1.0, how confident you are that this patch captures a reusable pattern."""


VALIDATE_GENERATE_PROMPT = """Based on the following skill patch content, generate a solution approach for the given problem. Reason purely from the skill patch's guidance — do NOT look at the actual code fix.

## Problem Statement
{problem_statement}

## Skill Patch Content
{patch_content}

---

Describe your solution approach in 3-5 steps. Focus on the STRATEGY (what structural changes to make and why), not specific implementation details like file names or line numbers.

Reply in this format:
APPROACH:
1. <step>
2. <step>
3. <step>
..."""


VALIDATE_COMPARE_PROMPT = """Compare the following two solution approaches for the same problem. Determine if they are strategically aligned — addressing the same root cause with compatible high-level strategies.

NOTE: Approach A is abstract (derived from a reusable pattern). Approach B is concrete (actual code changes). They should align at the STRATEGY level even if they differ in specificity. Do NOT penalize Approach A for being more abstract or generic.

## Problem Statement
{problem_statement}

## Approach A (generated from skill patch — abstract strategy)
{generated_approach}

## Approach B (ground truth — actual code changes)
{ground_truth_summary}

---

Reply in EXACTLY this JSON format:

```json
{{
  "consistent": true|false,
  "similarity": 0.0,
  "differences": ["<key difference 1>", "<key difference 2>"],
  "suggested_fix": "<if inconsistent, how to modify the skill patch content to better capture the pattern; empty string if consistent>"
}}
```

- "similarity": 0.0-1.0, strategic alignment of the two approaches (NOT surface-level detail match)
- "consistent": true if the core reasoning and strategy direction align (similarity >= 0.6)
- "suggested_fix": only if inconsistent, describe what to change in the patch content"""


REFINE_PATCH_PROMPT = """Refine the following skill patch content based on validation feedback.

## Original Patch Content
{original_content}

## Validation Feedback
{suggested_fix}

## Differences Found
{differences}

---

Output the refined markdown content only (no JSON wrapper, no frontmatter).
The content must have exactly three sections: ## Pattern Recognition, ## Root Cause, ## Solution Strategy."""


# =============================================================================
# Stage 2 Implementation
# =============================================================================

class PatchGenStage:
    """Generates and validates skill patches from PR dimensions."""

    def __init__(self, llm: LLMClient, embedder: LocalEmbedder):
        self.llm = llm
        self.embedder = embedder

    async def run(
        self,
        pr: PRData,
        instance: PRInstance,
        dimensions: List[Dict],
        taxonomy: Taxonomy,
    ) -> List[SkillPatch]:
        """Generate validated skill patches for all dimensions of a PR."""
        patches = []
        for dim in dimensions:
            patch = await self._process_dimension(pr, instance, dim, taxonomy)
            patches.append(patch)
        return patches

    async def _process_dimension(
        self,
        pr: PRData,
        instance: PRInstance,
        dim: Dict,
        taxonomy: Taxonomy,
    ) -> SkillPatch:
        """Generate and validate a single skill patch for one dimension."""
        dim_label = dim["label"]
        action_indices = dim["action_indices"]

        # Step 1: Generate patch
        raw_patch = await self._generate_patch(pr, instance, dim, taxonomy)

        # Step 2: Keep raw tags (with [CANDIDATE] markers) for Stage 3 visibility
        raw_tags = raw_patch.get("tags", {})
        tags = taxonomy.map_tags(raw_tags, skill_id=pr.instance_id)

        # Step 3: Validate against ground truth
        validated, note, content = await self._validate_patch(
            pr, raw_patch.get("content", "")
        )

        final_content = content or raw_patch.get("content", "")

        # Step 4: Compute embedding
        embedding = self.embedder.embed_single(final_content)

        return SkillPatch(
            source_pr_id=pr.instance_id,
            confidence_score=raw_patch.get("confidence_score", 0.0),
            tags=tags,
            content=final_content,
            dimension_label=dim_label,
            action_indices=action_indices,
            root_cause=instance.root_cause or "",
            validated=validated,
            validation_note=note,
            embedding=embedding,
        )

    async def _generate_patch(
        self,
        pr: PRData,
        instance: PRInstance,
        dim: Dict,
        taxonomy: Taxonomy,
    ) -> Dict[str, Any]:
        """Call LLM to generate a skill patch."""
        action_indices = dim["action_indices"]
        actions = [instance.actions[i] for i in action_indices if i < len(instance.actions)]

        actions_text = self._format_actions(actions, action_indices)
        decisions_text = self._format_decisions(instance)

        problem_excerpt = pr.problem_statement[:2000]

        prompt = GENERATE_PATCH_PROMPT.format(
            instance_id=pr.instance_id,
            repo=pr.repo,
            intent=instance.intent,
            problem_excerpt=problem_excerpt,
            root_cause=instance.root_cause or "(not identified)",
            cognitive_error=instance.cognitive_error or "(not identified)",
            actions_text=actions_text,
            decisions_text=decisions_text,
            domain_tags=taxonomy.get_tags_for_prompt("domain"),
            problem_pattern_tags=taxonomy.get_tags_for_prompt("problem_pattern"),
        )

        response = await self.llm.chat([
            {"role": "system", "content": "You are a skill patch generator. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ])

        return self._extract_json(response)

    async def _validate_patch(
        self,
        pr: PRData,
        patch_content: str,
    ) -> tuple:
        """Validate patch by comparing LLM-generated approach with ground truth.

        Returns (validated: bool, note: str, refined_content: str or None).
        """
        if not patch_content or not pr.patch:
            return False, "missing content or ground truth", None

        # Step 1: Generate solution approach from patch content
        gen_prompt = VALIDATE_GENERATE_PROMPT.format(
            problem_statement=pr.problem_statement[:3000],
            patch_content=patch_content,
        )
        generated_approach = await self.llm.chat([
            {"role": "system", "content": "You are a software engineer reasoning about a bug fix."},
            {"role": "user", "content": gen_prompt},
        ])

        # Step 2: Summarize ground truth patch
        gt_summary = pr.change_summary or pr.patch[:3000]

        # Step 3: Compare approaches
        cmp_prompt = VALIDATE_COMPARE_PROMPT.format(
            problem_statement=pr.problem_statement[:2000],
            generated_approach=generated_approach,
            ground_truth_summary=gt_summary,
        )
        cmp_response = await self.llm.chat([
            {"role": "system", "content": "You are a precise comparison judge. Output ONLY valid JSON."},
            {"role": "user", "content": cmp_prompt},
        ])
        cmp_result = self._extract_json(cmp_response)

        consistent = cmp_result.get("consistent", False)
        similarity = cmp_result.get("similarity", 0.0)
        note = f"similarity={similarity:.2f}"

        if consistent:
            return True, note, None

        # Step 4: Refine if inconsistent
        suggested_fix = cmp_result.get("suggested_fix", "")
        differences = cmp_result.get("differences", [])
        if suggested_fix:
            refine_prompt = REFINE_PATCH_PROMPT.format(
                original_content=patch_content,
                suggested_fix=suggested_fix,
                differences="\n".join(f"- {d}" for d in differences),
            )
            refined = await self.llm.chat([
                {"role": "system", "content": "You are refining a skill patch. Output ONLY the markdown content."},
                {"role": "user", "content": refine_prompt},
            ])
            return True, f"{note}, refined", refined.strip()

        return False, f"{note}, no fix suggested", None

    # =========================================================================
    # Formatting helpers
    # =========================================================================

    @staticmethod
    def _format_actions(actions, indices) -> str:
        if not actions:
            return "  (none)"
        order = {"core": 0, "supporting": 1, "cleanup": 2}
        lines = []
        for idx, a in zip(indices, actions):
            entry = (
                f"  [{idx}] ({a.importance}) [{a.type}] {a.action}\n"
                f"      Target: {a.target}\n"
                f"      Description: {a.description}\n"
                f"      Contribution: {a.contribution}"
            )
            lines.append(entry)
        return "\n".join(lines)

    @staticmethod
    def _format_decisions(instance: PRInstance) -> str:
        if not instance.decision_points:
            return "  (none)"
        return "\n".join(
            f"  - Problem: {d.problem}\n    Decision: {d.decision}\n    Rationale: {d.rationale}"
            for d in instance.decision_points
        )

    @staticmethod
    def _extract_json(response: str) -> Dict[str, Any]:
        """Extract JSON from LLM response."""
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
            return {}

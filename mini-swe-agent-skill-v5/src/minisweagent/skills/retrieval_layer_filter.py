"""Layer-filtered retrieval: return only a single layer of the skill hierarchy.

Ablation experiment 3: Test which layer contributes most value by isolating each:
  - scenario_only:         Only Layer 3 (specific scenario content)
  - domain_only:           Only Layer 2 (domain principles)
  - general_only:          Only Layer 1 (general principles from SKILL.md)
  - general_scenario:      Layer 1 + Layer 3 (skip domain, test L1+L3 combination)

Uses the same LLM-based category/scenario selection as the full system,
but only returns content from the specified layer(s).
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("retrieval_layer_filter")

from minisweagent.skills import _get_skills_dir
SKILLS_DIR = _get_skills_dir()

# Reuse the same selection prompt as the main system
_SELECTION_SYSTEM_PROMPT = """\
You are a skill-matching assistant. Given a software bug description and a list of \
available categories and scenarios, select the ONE category and ONE scenario that best \
matches the bug pattern.

Reply with ONLY a JSON object (no markdown fences, no explanation):
{"category": "<category_name>", "scenario": "<scenario_name>"}

If no scenario is a good match, reply: {"category": "", "scenario": ""}
"""


# ── Helpers (same as harbor_agent.py but self-contained) ─────────────────────


def _parse_frontmatter(filepath: Path):
    """Parse markdown file with optional YAML frontmatter."""
    if not filepath.exists():
        return None
    text = filepath.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            import yaml
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            return meta, body
    return {}, text


def _list_scenario_index(skills_dir: Path) -> str:
    """Build scenario index for LLM selection."""
    refs_dir = skills_dir / "references"
    if not refs_dir.exists():
        return ""
    lines = []
    for ref_file in sorted(refs_dir.glob("*.md")):
        category = ref_file.stem
        scenarios_dir = refs_dir / category / "scenarios"
        if scenarios_dir.exists():
            scenarios = [f.stem for f in sorted(scenarios_dir.glob("*.md"))]
            if scenarios:
                lines.append(f"- {category}: {', '.join(scenarios)}")
        else:
            lines.append(f"- {category}")
    return "\n".join(lines) if lines else ""


def _query_skill_selection(task: str, scenario_index: str, client, model_name: str):
    """Query LLM to select the best category/scenario."""
    user_content = (
        f"## Bug Description\n\n{task}\n\n"
        f"## Available Scenarios\n\n{scenario_index}\n\n"
        "Select the best matching category and scenario."
    )
    messages = [
        {"role": "system", "content": _SELECTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""
        if not content:
            return None
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            match = re.search(r"\{[^{}]*\}", content)
            if match:
                return json.loads(match.group(0))
    except Exception as e:
        logger.warning(f"Layer-filter skill selection failed: {e}")
    return None


def _load_general_principles(skills_dir: Path) -> str:
    """Load Layer 1: General principles from SKILL.md (Core Principles section only)."""
    skill_file = skills_dir / "SKILL.md"
    if not skill_file.exists():
        return ""
    parsed = _parse_frontmatter(skill_file)
    if not parsed:
        return ""
    _, body = parsed

    # Extract only the Core Principles section (before ## domain)
    match = re.search(r"(## Core Principles.*?)(?=\n## domain|\n## Domain|\Z)", body, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: return everything before first domain link
    lines = body.split("\n")
    result = []
    for line in lines:
        if line.strip().startswith("- [") and "references/" in line:
            break
        result.append(line)
    return "\n".join(result).strip()


def _load_domain_principles(skills_dir: Path, category: str) -> str:
    """Load Layer 2: Domain principles from references/[category].md."""
    ref_file = skills_dir / "references" / f"{category}.md"
    parsed = _parse_frontmatter(ref_file)
    if not parsed:
        return ""
    _, body = parsed
    # Try "## Domain Principles" first (old format), then "## Principles" (current format)
    match = re.search(r"(## (?:Domain )?Principles\s*\n.*?)(?=\n## |\Z)", body, re.DOTALL)
    return match.group(1).strip() if match else ""


def _load_scenario_content(skills_dir: Path, category: str, scenario: str) -> str:
    """Load Layer 3: Specific scenario content."""
    scenario_file = skills_dir / "references" / category / "scenarios" / f"{scenario}.md"
    parsed = _parse_frontmatter(scenario_file)
    if not parsed:
        return ""
    meta, body = parsed
    parts = []
    if meta.get("description"):
        parts.append(meta["description"])
    if body:
        parts.append(body)
    return "\n\n".join(parts) if parts else ""


# ── Public API ───────────────────────────────────────────────────────────────


def retrieve_layer_filtered(
    task: str,
    client,
    model_name: str,
    *,
    layer_mode: Optional[str] = None,
) -> str:
    """Retrieve skill content filtered to a single layer.

    Args:
        task: The current bug/task description.
        client: OpenAI-compatible client.
        model_name: Model name for LLM-based selection.
        layer_mode: One of "scenario_only", "domain_only", "general_only".
                    Defaults to env var MSWEA_LAYER_MODE.

    Returns:
        Formatted string with content from only the specified layer.
    """
    if layer_mode is None:
        layer_mode = os.environ.get("MSWEA_LAYER_MODE", "full")

    skills_dir_env = os.environ.get("MSWEA_SKILLS_DIR")
    skills_dir = Path(skills_dir_env) if skills_dir_env else SKILLS_DIR

    # ── General only: no LLM selection needed ──
    if layer_mode == "general_only":
        general = _load_general_principles(skills_dir)
        if general:
            return f"# Coding Principles\n\n{general}"
        return ""

    # ── Domain only / Scenario only: need LLM to select category/scenario ──
    scenario_index = _list_scenario_index(skills_dir)
    if not scenario_index:
        logger.warning("No scenario index available")
        # Fall back to general if we can't select
        if layer_mode == "domain_only":
            return ""
        return ""

    selection = _query_skill_selection(task, scenario_index, client, model_name)
    if not selection:
        logger.info("LLM selection returned nothing")
        return ""

    category = selection.get("category", "")
    scenario = selection.get("scenario", "")

    if layer_mode == "domain_only":
        if not category:
            return ""
        domain = _load_domain_principles(skills_dir, category)
        if domain:
            return f"# Domain Guidance: {category}\n\n{domain}"
        return ""

    if layer_mode == "scenario_only":
        if not category or not scenario:
            return ""
        sc = _load_scenario_content(skills_dir, category, scenario)
        if sc:
            return f"# Scenario Guidance: {category}/{scenario}\n\n{sc}"
        return ""

    if layer_mode == "general_scenario":
        # Layer 1 + Layer 3: Core Principles + Scenario (skip Domain)
        parts = []
        general = _load_general_principles(skills_dir)
        if general:
            parts.append(f"# Coding Principles\n\n{general}")
        if category and scenario:
            sc = _load_scenario_content(skills_dir, category, scenario)
            if sc:
                parts.append(f"# Scenario Guidance: {category}/{scenario}\n\n{sc}")
        return "\n\n".join(parts) if parts else ""

    # Should not reach here, but return empty
    logger.warning(f"Unknown layer_mode: {layer_mode}")
    return ""


def reset_cache():
    """No persistent cache in this module, placeholder for interface consistency."""
    pass

"""Skill loading module for mini-swe-agent.

Directory layout:
  skills/SKILL.md                              ← main skill entry point
  skills/references/<category>.md              ← category guides
  skills/references/<category>/scenarios/*.md  ← detailed scenarios

Public API:
  skill_read(name) — "list" returns scenario index, category returns patterns+scenarios, category/scenario returns full scenario
  load_skills_summary() — summary string for system prompt injection
  load_core_principles() — compact core principles for system prompt injection
  list_skills() — [{name, description}] for system prompt skill listing
"""

import logging
import os
import re
from pathlib import Path

import yaml

logger = logging.getLogger("minisweagent.skills")

_PACKAGE_SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"


def _get_skills_dir() -> Path:
    """Resolve skills directory with priority: env var > cwd/skills > package bundled."""
    env = os.getenv("MSWEA_SKILLS_DIR")
    if env:
        return Path(env)

    cwd_skills = Path.cwd() / "skills"
    if cwd_skills.is_dir():
        return cwd_skills

    return _PACKAGE_SKILLS_DIR


def _parse_frontmatter(path: Path) -> tuple[dict, str] | None:
    """Parse a markdown file with optional YAML frontmatter. Returns (metadata, body) or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].strip()

    return {}, text.strip()


def _find_main_skill(skills_dir: Path) -> tuple[dict, str] | None:
    """Read the main SKILL.md."""
    for fname in ("SKILL.md", "skill.md"):
        f = skills_dir / fname
        if f.is_file():
            return _parse_frontmatter(f)
    return None


def _list_references(skills_dir: Path) -> list[dict]:
    """List all reference categories under skills/references/."""
    refs_dir = skills_dir / "references"
    if not refs_dir.is_dir():
        return []
    result = []
    for f in sorted(refs_dir.iterdir()):
        if f.is_file() and f.suffix == ".md":
            parsed = _parse_frontmatter(f)
            if parsed:
                meta, body = parsed
                result.append({
                    "name": meta.get("name", f.stem),
                    "description": meta.get("description", ""),
                    "tags": meta.get("tags", []),
                })
    return result


def _list_scenarios(skills_dir: Path, category: str) -> list[str]:
    """List scenario names under a category."""
    scenarios_dir = skills_dir / "references" / category / "scenarios"
    if not scenarios_dir.is_dir():
        return []
    return sorted(f.stem for f in scenarios_dir.iterdir() if f.is_file() and f.suffix == ".md")


def _extract_scenario_summary(scenario_path: Path, max_len: int = 120) -> str:
    """Extract the first meaningful sentence from a scenario file as a summary."""
    try:
        for line in scenario_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("---") and not line.startswith("- "):
                return line[:max_len] + ("..." if len(line) > max_len else "")
    except OSError:
        pass
    return ""


def _get_scenario_with_summary(skills_dir: Path, category: str, scenario: str) -> str:
    """Return 'category/scenario: summary' string."""
    path = skills_dir / "references" / category / "scenarios" / f"{scenario}.md"
    summary = _extract_scenario_summary(path)
    if summary:
        return f"  - `{category}/{scenario}`: {summary}"
    return f"  - `{category}/{scenario}`"


def _skill_enforcement_notice() -> str:
    """Return practical guidance on how to apply a scenario."""
    return (
        "\n---\n"
        "## How to apply this scenario\n"
        "1. Compare the **Problem Description** above with the current bug — confirm the pattern matches\n"
        "2. Use the **Root Cause Analysis** to predict where the bug is BEFORE reading source code\n"
        "3. Follow the **解决步骤** (Solution Steps) to locate and fix the bug\n"
        "4. Check **Boundary Cases** to ensure your fix covers edge cases\n"
    )


# ── Public API ──────────────────────────────────────────────────────────


def load_core_principles() -> str:
    """Extract the full Core Principles section from SKILL.md.

    Returns everything between '## Core Principles' and the next '## ' heading.
    """
    skills_dir = _get_skills_dir()
    main = _find_main_skill(skills_dir)
    if not main:
        return ""
    _, body = main

    # Extract from "## Core Principles" up to the next ## heading (or end of file)
    principles_match = re.search(
        r"(## Core Principles\s*\n.*?)(?=\n## |\Z)", body, re.DOTALL
    )
    if not principles_match:
        return ""

    return principles_match.group(1).strip()


def list_skills() -> list[dict]:
    """Return [{name, description}] from SKILL.md for system prompt and _build_system_prompt()."""
    skills_dir = _get_skills_dir()
    main = _find_main_skill(skills_dir)
    if not main:
        return []
    meta, _ = main
    name = meta.get("name", "")
    description = meta.get("description", "")
    if not name:
        return []
    return [{"name": name, "description": description}]


def load_skills_summary() -> str:
    """Load a summary string for system prompt injection."""
    skills_dir = _get_skills_dir()
    main = _find_main_skill(skills_dir)
    if not main:
        return ""
    meta, _ = main
    refs = _list_references(skills_dir)
    lines = []
    if meta.get("name"):
        lines.append(f"Skill: {meta['name']}")
    if meta.get("description"):
        lines.append(f"  {meta['description']}")
    if refs:
        lines.append("References:")
        for r in refs:
            line = f"  - {r['name']}: {r['description']}"
            if r.get("tags"):
                line += f" [{', '.join(r['tags'])}]"
            lines.append(line)
    return "\n".join(lines)


def skill_read(name: str) -> str:
    """Read skill content by name.

    - "list" or main skill name → flattened scenario index grouped by category (with summaries)
    - "<category>" → category patterns + scenarios with summaries
    - "<category>/<scenario>" → specific scenario content
    """
    skills_dir = _get_skills_dir()

    # ── List mode: return flattened scenario index ──
    main = _find_main_skill(skills_dir)
    if name == "list" or (main and main[0].get("name") == name):
        if not main:
            return "No skills available."

        parts = []
        parts.append("# Scenario Index")
        parts.append(
            "Below is the full index of bug-pattern scenarios grouped by category. "
            "Scan the summaries to find the scenario that best matches the current bug, "
            "then call `skill_read(\"<category>/<scenario>\")` to read the full scenario.\n"
        )

        refs = _list_references(skills_dir)
        for ref in refs:
            cat_name = ref["name"]
            cat_desc = ref["description"]
            scenarios = _list_scenarios(skills_dir, cat_name)
            if not scenarios:
                continue
            parts.append(f"## {cat_name}")
            if cat_desc:
                parts.append(f"_{cat_desc}_\n")
            for s in scenarios:
                parts.append(_get_scenario_with_summary(skills_dir, cat_name, s))
            parts.append("")

        parts.append(
            "---\n"
            "**Next step**: Pick the 1-2 scenarios that best match the current bug and call "
            "`skill_read(\"<category>/<scenario>\")` to get the full expert analysis."
        )
        return "\n".join(parts)

    # ── Category mode: return patterns + scenarios with summaries ──
    ref_file = skills_dir / "references" / f"{name}.md"
    parsed = _parse_frontmatter(ref_file)
    if parsed:
        meta, body = parsed
        parts = []
        if meta.get("name"):
            parts.append(f"# {meta['name']}")
        if meta.get("description"):
            parts.append(meta["description"])
        parts.append("")
        parts.append(body)
        # List scenarios with summaries
        scenarios = _list_scenarios(skills_dir, name)
        if scenarios:
            parts.append("\n## Available Scenarios")
            parts.append(
                f"Call `skill_read(\"{name}/<scenario>\")` to read a specific scenario:\n"
            )
            for s in scenarios:
                parts.append(_get_scenario_with_summary(skills_dir, name, s))
        parts.append(
            "\n---\n"
            "**Next step**: Pick the scenario that best matches the current bug and call "
            f"`skill_read(\"{name}/<scenario>\")` to get the full expert analysis."
        )
        return "\n".join(parts)

    # ── Scenario mode: return full scenario content ──
    if "/" in name:
        category, scenario = name.split("/", 1)
        scenario_file = skills_dir / "references" / category / "scenarios" / f"{scenario}.md"
        parsed = _parse_frontmatter(scenario_file)
        if parsed:
            meta, body = parsed
            parts = []
            title = meta.get("name", scenario)
            parts.append(f"# Scenario: {title}")
            if meta.get("description"):
                parts.append(meta["description"])
            parts.append("")
            parts.append(body)
            parts.append(_skill_enforcement_notice())
            return "\n".join(parts)

    # ── Not found ──
    refs = _list_references(skills_dir)
    msg = f"Error: '{name}' not found."
    if refs:
        msg += "\n\nAvailable categories:\n" + "\n".join(
            f"  - {r['name']}: {r['description']}" for r in refs
        )
    return msg

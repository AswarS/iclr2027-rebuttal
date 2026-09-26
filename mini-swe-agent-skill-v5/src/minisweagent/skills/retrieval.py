"""Skill retrieval sub-agent.

Before the main agent starts working on a task, this module queries the model
to identify the most relevant skill content from the 3-layer hierarchy:
  Layer 1: SKILL.md (general principles)
  Layer 2: references/[domain].md (domain principles)
  Layer 3: references/[domain]/scenarios/*.md (specific scenario)

The combined content is returned as a single string for injection as a user message.
"""

import json
import logging
import re

from minisweagent.skills import (
    _find_main_skill,
    _get_skills_dir,
    _list_references,
    _list_scenarios,
    _parse_frontmatter,
    load_core_principles,
    skill_read,
)

logger = logging.getLogger("minisweagent.skills.retrieval")

_SELECTION_SYSTEM_PROMPT = """\
You are a skill-matching assistant. Given a software bug description and a list of \
available categories and scenarios, select the ONE category and ONE scenario that best \
matches the bug pattern.

Reply with ONLY a JSON object (no markdown fences, no explanation):
{"category": "<category_name>", "scenario": "<scenario_name>"}

If no scenario is a good match, reply: {"category": "", "scenario": ""}
"""


def retrieve_skill_content(task: str, model) -> str:
    """Run the skill retrieval sub-agent.

    Args:
        task: The SWE-bench task/problem description.
        model: A model instance (same as the main agent uses).

    Returns:
        Combined skill content string with ## section headers,
        or empty string if skills are unavailable or retrieval fails.
    """
    skills_dir = _get_skills_dir()
    main = _find_main_skill(skills_dir)
    if not main:
        logger.debug("No SKILL.md found, skipping skill retrieval")
        return ""

    # Layer 1: General principles
    general_principles = load_core_principles()

    # Build the scenario index for the model to choose from
    scenario_index = skill_read("list")
    if not scenario_index or scenario_index == "No skills available.":
        logger.debug("No skill scenarios available")
        return general_principles if general_principles else ""

    # Query the model to select the best matching category/scenario
    selection = _query_model_for_selection(task, scenario_index, model)
    if not selection:
        logger.info("Sub-agent returned no selection, using general principles only")
        return general_principles if general_principles else ""

    category = selection.get("category", "")
    scenario = selection.get("scenario", "")

    # Build combined content
    parts = []

    # Section 1: General Principles
    if general_principles:
        parts.append(general_principles)

    # Section 2: Domain principles
    if category:
        domain_content = _load_domain_content(skills_dir, category)
        if domain_content:
            parts.append(f"## Domain: {category}\n\n{domain_content}")

    # Section 3: Specific scenario
    if category and scenario:
        scenario_content = _load_scenario_content(skills_dir, category, scenario)
        if scenario_content:
            parts.append(f"## Scenario: {scenario}\n\n{scenario_content}")

    if not parts:
        return ""

    return "\n\n".join(parts)


def _query_model_for_selection(task: str, scenario_index: str, model) -> dict | None:
    """Query the model to select the best category/scenario for the task."""
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
        client = getattr(model, "client", None)
        if client is not None:
            # OpenAICustomModel path — use the client directly
            response = client.chat.completions.create(
                model=model.config.model_name,
                messages=messages,
                temperature=0.0,
            )
        else:
            # LitellmModel path — use litellm.completion
            import litellm

            response = litellm.completion(
                model=model.config.model_name,
                messages=messages,
                temperature=0.0,
            )
        content = response.choices[0].message.content or ""
        if not content:
            return None
        return _parse_json_response(content)
    except Exception as e:
        logger.warning(f"Skill retrieval sub-agent failed: {e}")
        return None


def _parse_json_response(content: str) -> dict | None:
    """Extract JSON from the model's response."""
    # Try direct parse
    try:
        result = json.loads(content.strip())
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding any JSON object in the text
    match = re.search(r"\{[^{}]*\}", content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _load_domain_content(skills_dir, category: str) -> str:
    """Load domain principles from references/[category].md.

    Extracts content between '## Domain Principles' and '## Patterns'.
    """
    ref_file = skills_dir / "references" / f"{category}.md"
    parsed = _parse_frontmatter(ref_file)
    if not parsed:
        return ""
    _, body = parsed

    # Extract "## Domain Principles" section up to "## Patterns" or next ## heading
    match = re.search(
        r"(## Domain Principles\s*\n.*?)(?=\n## |\Z)", body, re.DOTALL
    )
    if not match:
        return ""
    return match.group(1).strip()


def _load_scenario_content(skills_dir, category: str, scenario: str) -> str:
    """Load specific scenario content from references/[category]/scenarios/[scenario].md."""
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

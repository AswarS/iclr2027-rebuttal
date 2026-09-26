"""Tests for skill retrieval sub-agent content assembly."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from minisweagent.skills.retrieval import retrieve_skill_content


@pytest.fixture
def skills_dir(tmp_path):
    """Create a minimal skills directory structure."""
    # Layer 1: SKILL.md
    (tmp_path / "SKILL.md").write_text(
        "---\nname: test-skills\ndescription: Test skills\n---\n"
        "## Core Principles\n\n"
        "### 1. Reproduce First\n"
        "Always reproduce before fixing.\n\n"
        "### 2. Read the Error\n"
        "Read the full traceback before guessing.\n\n"
        "## Categories\n\nSee references/\n",
        encoding="utf-8",
    )

    # Layer 2: references/python.md
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "python.md").write_text(
        "---\nname: python\ndescription: Python bug patterns\n---\n\n"
        "## Domain Principles\n\n"
        "1. Look for off-by-one errors.\n"
        "2. Check type mismatches.\n\n"
        "## Patterns\n\n"
        "### Off-by-one\n"
        "Loop bounds are wrong.\n",
        encoding="utf-8",
    )

    # Layer 3: references/python/scenarios/off_by_one.md
    scenarios = refs / "python" / "scenarios"
    scenarios.mkdir(parents=True)
    (scenarios / "off_by_one.md").write_text(
        "---\nname: Off-by-one\ndescription: Index out of range\n---\n"
        "Check loop bounds carefully.",
        encoding="utf-8",
    )

    return tmp_path


def _make_model_without_client(category: str, scenario: str):
    """Build a mock model (no .client) that returns the given category/scenario via litellm path."""
    response = MagicMock()
    response.choices[0].message.content = json.dumps({"category": category, "scenario": scenario})

    # spec limits attributes — accessing .client will raise AttributeError,
    # so getattr(model, "client", None) returns None.
    model = MagicMock(spec=["config"])
    model.config.model_name = "test-model"

    return model, response


class TestRetrieveSkillContent:
    def test_no_skills_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSWEA_SKILLS_DIR", str(tmp_path / "nonexistent"))
        model = MagicMock(spec=["config"])
        assert retrieve_skill_content("some task", model) == ""

    def test_no_skill_md_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSWEA_SKILLS_DIR", str(tmp_path))
        model = MagicMock(spec=["config"])
        assert retrieve_skill_content("some task", model) == ""

    def test_full_three_layer_content(self, skills_dir, monkeypatch):
        monkeypatch.setenv("MSWEA_SKILLS_DIR", str(skills_dir))
        model, response = _make_model_without_client("python", "off_by_one")

        with patch("litellm.completion", return_value=response):
            result = retrieve_skill_content("list index out of range bug", model)

        # Layer 1: full Core Principles section
        assert "## Core Principles" in result
        assert "### 1. Reproduce First" in result
        assert "Always reproduce before fixing." in result
        assert "### 2. Read the Error" in result

        # Layer 2: domain principles only (not Patterns section)
        assert "## Domain: python" in result
        assert "## Domain Principles" in result
        assert "off-by-one errors" in result
        assert "type mismatches" in result
        assert "## Patterns" not in result
        assert "Loop bounds are wrong" not in result

        # Layer 3: scenario section
        assert "## Scenario: off_by_one" in result
        assert "Check loop bounds carefully." in result

        # Sections appear in order
        pos_principles = result.index("## Core Principles")
        pos_domain = result.index("## Domain: python")
        pos_scenario = result.index("## Scenario: off_by_one")
        assert pos_principles < pos_domain < pos_scenario

    def test_no_matching_scenario_returns_general_only(self, skills_dir, monkeypatch):
        monkeypatch.setenv("MSWEA_SKILLS_DIR", str(skills_dir))
        model, response = _make_model_without_client("", "")

        with patch("litellm.completion", return_value=response):
            result = retrieve_skill_content("unrelated task", model)

        assert "## Core Principles" in result
        assert "## Domain:" not in result
        assert "## Scenario:" not in result

    def test_model_failure_returns_general_only(self, skills_dir, monkeypatch):
        monkeypatch.setenv("MSWEA_SKILLS_DIR", str(skills_dir))
        model = MagicMock(spec=["config"])
        model.config.model_name = "test-model"

        with patch("litellm.completion", side_effect=RuntimeError("API error")):
            result = retrieve_skill_content("some task", model)

        assert "## Core Principles" in result
        assert "## Domain:" not in result

    def test_uses_openai_client_when_available(self, skills_dir, monkeypatch):
        monkeypatch.setenv("MSWEA_SKILLS_DIR", str(skills_dir))
        response = MagicMock()
        response.choices[0].message.content = json.dumps({"category": "python", "scenario": "off_by_one"})

        model = MagicMock()
        model.config.model_name = "test-model"
        model.client.chat.completions.create.return_value = response

        result = retrieve_skill_content("index error", model)

        model.client.chat.completions.create.assert_called_once()
        assert "## Domain: python" in result
        assert "## Scenario: off_by_one" in result

    def test_section_separator_is_double_newline(self, skills_dir, monkeypatch):
        monkeypatch.setenv("MSWEA_SKILLS_DIR", str(skills_dir))
        model, response = _make_model_without_client("python", "off_by_one")

        with patch("litellm.completion", return_value=response):
            result = retrieve_skill_content("bug", model)

        # Sections are joined with "\n\n"
        assert "\n\n## Domain:" in result
        assert "\n\n## Scenario:" in result

    def test_print_full_assembled_content(self, skills_dir, monkeypatch):
        """Print the full assembled skill content for visual inspection.

        Run with: pytest tests/skills/test_retrieval.py -s -k test_print
        """
        monkeypatch.setenv("MSWEA_SKILLS_DIR", str(skills_dir))
        model, response = _make_model_without_client("python", "off_by_one")

        with patch("litellm.completion", return_value=response):
            result = retrieve_skill_content("list index out of range in loop", model)

        print("\n" + "=" * 70)
        print("ASSEMBLED SKILL CONTENT (injected as user message before task)")
        print("=" * 70)
        print(result)
        print("=" * 70)
        print(f"Total length: {len(result)} chars")
        print("=" * 70 + "\n")

        assert result  # non-empty

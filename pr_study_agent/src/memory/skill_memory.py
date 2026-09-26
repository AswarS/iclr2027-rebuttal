"""Skill storage — directory-based format per design spec §3.2.

Each skill is stored as:
    <skill-name>/
        SKILL.md        # core definition (YAML frontmatter + markdown body)
        examples/       # PR instances that contributed
        scripts/        # optional executable helpers
        resources/      # reference documents
"""

import json
import re
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field, asdict


@dataclass
class Skill:
    """Skill index entry."""
    id: str
    name: str  # kebab-case directory name
    description: str  # generalized capability, NOT a single PR intent
    tags: Dict[str, List[str]] = field(default_factory=lambda: {
        "domain": [], "problem_pattern": []
    })
    version: int = 1  # incremented on each update
    trigger: str = ""  # when to use
    workflow: List[str] = field(default_factory=list)
    heuristics: List[str] = field(default_factory=list)
    examples_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def tags_flat(self) -> List[str]:
        """Flatten tags into a single list."""
        if isinstance(self.tags, dict):
            result = []
            for dim_tags in self.tags.values():
                if isinstance(dim_tags, list):
                    result.extend(dim_tags)
            return result
        # Legacy: tags is already a flat list
        return self.tags if isinstance(self.tags, list) else []


class SkillMemory:
    """Manages directory-based skill storage and indexing."""

    def __init__(self, index_path: str, skills_dir: str):
        self.index_path = Path(index_path)
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_index()

    def _ensure_index(self) -> None:
        if not self.index_path.exists():
            self._save_index([])

    def _load_index(self) -> List[Dict[str, Any]]:
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_index(self, index: List[Dict[str, Any]]) -> None:
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def _skill_dir(self, skill_name: str) -> Path:
        return self.skills_dir / skill_name

    def add_skill(self, skill: Skill, skill_md_body: str, pr_instance_dict: Dict[str, Any]) -> str:
        """Create a new skill directory with SKILL.md and first example.

        Returns the skill directory path.
        """
        skill_dir = self._skill_dir(skill.name)
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "examples").mkdir(exist_ok=True)
        (skill_dir / "scripts").mkdir(exist_ok=True)
        (skill_dir / "resources").mkdir(exist_ok=True)

        # Write SKILL.md with YAML frontmatter
        skill_md_content = self._build_skill_md(skill, skill_md_body)
        with open(skill_dir / "SKILL.md", "w", encoding="utf-8") as f:
            f.write(skill_md_content)

        # Write first example
        instance_id = pr_instance_dict.get("instance_id", "unknown")
        example_file = skill_dir / "examples" / f"{self._safe_filename(instance_id)}.md"
        with open(example_file, "w", encoding="utf-8") as f:
            f.write(self._format_example(pr_instance_dict))

        skill.examples_count = 1

        # Update index
        index = self._load_index()
        index.append(asdict(skill))
        self._save_index(index)

        return str(skill_dir)

    def update_skill(self, skill_id: str, skill_md_body: str, pr_instance_dict: Dict[str, Any],
                     updated_fields: Optional[Dict[str, Any]] = None) -> str:
        """Update an existing skill's SKILL.md and add a new example.

        Returns the skill directory path.
        """
        index = self._load_index()
        for entry in index:
            if entry["id"] == skill_id:
                skill_dir = self._skill_dir(entry["name"])

                # Ensure new directories exist (migration from old format)
                (skill_dir / "scripts").mkdir(exist_ok=True)
                (skill_dir / "resources").mkdir(exist_ok=True)

                # Update index entry
                entry["examples_count"] = entry.get("examples_count", 0) + 1
                entry["version"] = entry.get("version", 1) + 1
                entry["updated_at"] = datetime.now().isoformat()
                if updated_fields:
                    for k, v in updated_fields.items():
                        if k in entry:
                            entry[k] = v

                # Build Skill object for frontmatter
                skill = Skill(
                    id=entry["id"],
                    name=entry["name"],
                    description=entry.get("description", ""),
                    tags=entry.get("tags", []),
                    version=entry["version"],
                )

                # Overwrite SKILL.md with frontmatter
                skill_md_content = self._build_skill_md(skill, skill_md_body)
                with open(skill_dir / "SKILL.md", "w", encoding="utf-8") as f:
                    f.write(skill_md_content)

                # Add example
                (skill_dir / "examples").mkdir(exist_ok=True)
                instance_id = pr_instance_dict.get("instance_id", "unknown")
                example_file = skill_dir / "examples" / f"{self._safe_filename(instance_id)}.md"
                with open(example_file, "w", encoding="utf-8") as f:
                    f.write(self._format_example(pr_instance_dict))

                self._save_index(index)
                return str(skill_dir)

        raise ValueError(f"Skill {skill_id} not found in index")

    def load_skill_content(self, skill_name: str) -> str:
        """Read SKILL.md body content (without frontmatter) for a skill."""
        skill_file = self._skill_dir(skill_name) / "SKILL.md"
        if skill_file.exists():
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()
            return self._strip_frontmatter(content)
        return ""

    def load_skill_raw(self, skill_name: str) -> str:
        """Read full SKILL.md content (with frontmatter) for a skill."""
        skill_file = self._skill_dir(skill_name) / "SKILL.md"
        if skill_file.exists():
            with open(skill_file, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def update_skill_tags(self, skill_id: str, tags: Dict[str, List[str]]) -> None:
        """Update a skill's tags in the index and regenerate its SKILL.md frontmatter."""
        index = self._load_index()
        for entry in index:
            if entry["id"] == skill_id:
                entry["tags"] = tags

                # Rebuild SKILL.md with updated frontmatter
                skill_dir = self._skill_dir(entry["name"])
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    with open(skill_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    body = self._strip_frontmatter(content)
                    skill = Skill(
                        id=entry["id"],
                        name=entry["name"],
                        description=entry.get("description", ""),
                        tags=tags,
                        version=entry.get("version", 1),
                    )
                    with open(skill_file, "w", encoding="utf-8") as f:
                        f.write(self._build_skill_md(skill, body))

                self._save_index(index)
                return
        raise ValueError(f"Skill {skill_id} not found in index")

    def list_skills(self) -> List[Skill]:
        """Return all skills from index."""
        index = self._load_index()
        skills = []
        for data in index:
            skills.append(Skill(
                id=data.get("id", ""),
                name=data.get("name", ""),
                description=data.get("description", ""),
                tags=data.get("tags", []),
                version=data.get("version", 1),
                trigger=data.get("trigger", ""),
                workflow=data.get("workflow", []),
                heuristics=data.get("heuristics", []),
                examples_count=data.get("examples_count", 0),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            ))
        return skills

    def get_processed_prs(self) -> set:
        """Get set of instance_ids from all example files across all skills."""
        processed = set()
        for skill_dir in self.skills_dir.iterdir():
            examples_dir = skill_dir / "examples"
            if examples_dir.is_dir():
                for example_file in examples_dir.glob("*.md"):
                    processed.add(example_file.stem)
        return processed

    def count(self) -> int:
        return len(self._load_index())

    @staticmethod
    def _safe_filename(instance_id: str) -> str:
        """Convert instance_id to safe filename (replace / with __)."""
        return re.sub(r'[/\\:]', '__', instance_id)

    @staticmethod
    def _format_example(pr_instance_dict: Dict[str, Any]) -> str:
        """Format a PR instance dict as a markdown example file."""
        lines = [f"# {pr_instance_dict.get('instance_id', 'unknown')}", ""]
        lines.append(f"**Repo:** {pr_instance_dict.get('repo', '')}")
        lines.append(f"**Intent:** {pr_instance_dict.get('intent', '')}")
        lines.append("")

        # New semantic actions format
        actions = pr_instance_dict.get("actions", [])
        if actions:
            lines.append("## Actions")
            for i, a in enumerate(actions):
                importance = a.get("importance", "core")
                lines.append(f"### [{i}] ({importance}) {a.get('action', '')}")
                lines.append(f"- **Type:** {a.get('type', '')}")
                lines.append(f"- **Target:** {a.get('target', '')}")
                lines.append(f"- **Description:** {a.get('description', '')}")
                lines.append(f"- **Contribution:** {a.get('contribution', '')}")
                files = a.get("files", [])
                if files:
                    lines.append(f"- **Files:** {', '.join(files)}")
                lines.append("")

        deps = pr_instance_dict.get("action_dependencies", [])
        if deps:
            lines.append("## Action Dependencies")
            for d in deps:
                lines.append(f"- Action [{d.get('from_action', '?')}] → Action [{d.get('to_action', '?')}]: {d.get('reason', '')}")
            lines.append("")

        # Backward compat: render old changes format if present (no actions)
        if not actions:
            changes = pr_instance_dict.get("changes", [])
            if changes:
                lines.append("## Changes (legacy)")
                for c in changes:
                    lines.append(f"- [{c.get('type', '')}] `{c.get('target', '')}`: {c.get('description', '')}")
                lines.append("")

        decisions = pr_instance_dict.get("decision_points", [])
        if decisions:
            lines.append("## Decision Points")
            for d in decisions:
                lines.append(f"- **Problem:** {d.get('problem', '')}")
                lines.append(f"  **Decision:** {d.get('decision', '')}")
                lines.append(f"  **Rationale:** {d.get('rationale', '')}")
            lines.append("")

        outcome = pr_instance_dict.get("outcome", {})
        if outcome.get("summary"):
            lines.append("## Outcome")
            lines.append(outcome["summary"])
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _build_skill_md(skill: Skill, body: str) -> str:
        """Build SKILL.md content with YAML frontmatter + markdown body."""
        if isinstance(skill.tags, dict):
            tags_lines = "\n".join(
                f"  {dim}: [{', '.join(tags)}]"
                for dim, tags in skill.tags.items()
                if tags
            )
            tags_block = f"tags:\n{tags_lines}" if tags_lines else "tags: {}"
        else:
            # Legacy flat list
            tags_str = ", ".join(skill.tags) if skill.tags else ""
            tags_block = f"tags: [{tags_str}]"

        frontmatter = (
            f"---\n"
            f"id: {skill.id}\n"
            f"name: {skill.name}\n"
            f"description: {skill.description}\n"
            f"{tags_block}\n"
            f"version: {skill.version}\n"
            f"---\n"
        )
        return frontmatter + "\n" + body.strip() + "\n"

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Remove YAML frontmatter from SKILL.md content, return body only."""
        match = re.match(r'^---\s*\n.*?\n---\s*\n', content, re.DOTALL)
        if match:
            return content[match.end():].strip()
        return content.strip()

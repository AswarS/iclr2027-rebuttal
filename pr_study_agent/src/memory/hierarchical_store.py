"""Hierarchical three-layer skill storage.

Layer 1: SKILL.md              — 跨领域通用原则 (总纲领)
Layer 2: references/[domain].md — 特定领域最佳实践
Layer 3: references/[domain]/scenarios/[scenario].md — 具体场景解决方案

Also manages patch_pool/ for intermediate Stage 2 outputs.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


class HierarchicalStore:
    """Manages the three-layer skill file hierarchy and patch pool."""

    def __init__(self, skills_dir: str, patch_pool_dir: str = ""):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.refs_dir = self.skills_dir / "references"
        self.refs_dir.mkdir(parents=True, exist_ok=True)
        self.patch_pool_dir = Path(patch_pool_dir) if patch_pool_dir else self.skills_dir / "patch_pool"
        self.patch_pool_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Layer 1: SKILL.md (总纲领)
    # =========================================================================

    def read_skill_md(self) -> str:
        """Read the top-level SKILL.md content."""
        path = self.skills_dir / "SKILL.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def write_skill_md(self, content: str) -> None:
        """Write the top-level SKILL.md."""
        path = self.skills_dir / "SKILL.md"
        path.write_text(content, encoding="utf-8")

    # =========================================================================
    # Layer 2: references/[domain].md
    # =========================================================================

    def read_domain_md(self, domain: str) -> str:
        """Read a domain-level reference file."""
        path = self.refs_dir / f"{domain}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def write_domain_md(self, domain: str, content: str) -> None:
        """Write a domain-level reference file."""
        path = self.refs_dir / f"{domain}.md"
        path.write_text(content, encoding="utf-8")

    def list_domains(self) -> List[str]:
        """List all domain names (from .md files in references/)."""
        return [
            p.stem for p in self.refs_dir.glob("*.md")
        ]

    # =========================================================================
    # Layer 3: references/[domain]/scenarios/[scenario].md
    # =========================================================================

    def read_scenario_md(self, domain: str, scenario: str) -> str:
        """Read a scenario file."""
        path = self.refs_dir / domain / "scenarios" / f"{scenario}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def write_scenario_md(self, domain: str, scenario: str, content: str) -> None:
        """Write a scenario file, creating directories as needed."""
        scenario_dir = self.refs_dir / domain / "scenarios"
        scenario_dir.mkdir(parents=True, exist_ok=True)
        path = scenario_dir / f"{scenario}.md"
        path.write_text(content, encoding="utf-8")

    def list_scenarios(self, domain: str) -> List[str]:
        """List all scenario names for a domain."""
        scenario_dir = self.refs_dir / domain / "scenarios"
        if not scenario_dir.exists():
            return []
        return [p.stem for p in scenario_dir.glob("*.md")]

    def delete_scenario(self, domain: str, scenario: str) -> bool:
        """Delete a scenario file. Returns True if file existed and was deleted."""
        path = self.refs_dir / domain / "scenarios" / f"{scenario}.md"
        if path.exists():
            path.unlink()
            return True
        return False

    # =========================================================================
    # Patch Pool (Stage 2 中间产物)
    # =========================================================================

    def save_patch(self, patch_data: Dict[str, Any]) -> str:
        """Save a skill patch to the pool. Returns the file path."""
        pr_id = patch_data.get("source_pr_id", "unknown").replace("/", "__")
        dim = patch_data.get("dimension_label", "dim").replace(" ", "-")
        filename = f"{pr_id}__{dim}.json"
        path = self.patch_pool_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(patch_data, f, ensure_ascii=False, indent=2)
        return str(path)

    def load_all_patches(self) -> List[Dict[str, Any]]:
        """Load all patches from the pool."""
        patches = []
        for path in sorted(self.patch_pool_dir.glob("*.json")):
            with open(path, "r", encoding="utf-8") as f:
                patches.append(json.load(f))
        return patches

    def clear_patch_pool(self) -> int:
        """Remove all patches from the pool. Returns count removed."""
        count = 0
        for path in self.patch_pool_dir.glob("*.json"):
            path.unlink()
            count += 1
        return count

    # =========================================================================
    # Validation helpers
    # =========================================================================

    def validate_links(self) -> List[str]:
        """Check that all markdown links in SKILL.md point to existing files.

        Returns list of broken link descriptions.
        """
        broken = []
        skill_md = self.read_skill_md()
        # Find markdown links like [text](references/xxx.md)
        for match in re.finditer(r'\[([^\]]*)\]\(([^)]+)\)', skill_md):
            link_text, link_path = match.group(1), match.group(2)
            full_path = self.skills_dir / link_path
            if not full_path.exists():
                broken.append(f"SKILL.md: [{link_text}]({link_path}) -> file not found")

        # Check domain files for scenario links
        for domain in self.list_domains():
            domain_content = self.read_domain_md(domain)
            for match in re.finditer(r'\[([^\]]*)\]\(([^)]+)\)', domain_content):
                link_text, link_path = match.group(1), match.group(2)
                full_path = self.refs_dir / link_path
                if not full_path.exists():
                    broken.append(f"references/{domain}.md: [{link_text}]({link_path}) -> file not found")

        return broken

    def get_stats(self) -> Dict[str, Any]:
        """Return statistics about the hierarchical store."""
        domains = self.list_domains()
        total_scenarios = sum(len(self.list_scenarios(d)) for d in domains)
        patch_count = len(list(self.patch_pool_dir.glob("*.json")))
        return {
            "has_skill_md": (self.skills_dir / "SKILL.md").exists(),
            "domain_count": len(domains),
            "domains": domains,
            "scenario_count": total_scenarios,
            "patch_pool_count": patch_count,
        }

"""Taxonomy management — controlled vocabulary for two-dimensional skill tags.

Dimensions:
  1. domain: problem category (structural bug class, NOT language/framework)
  2. problem_pattern: root cause logic

Tags are mapped to the taxonomy via exact match → fuzzy match → candidate pool.
"""

import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from datetime import datetime


DIMENSIONS = ["domain", "problem_pattern"]


class Taxonomy:
    """Manages the four-dimensional tag taxonomy and candidate pool."""

    def __init__(self, taxonomy_path: str):
        self.path = Path(taxonomy_path)
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load taxonomy from JSON file."""
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {
                dim: {"description": "", "tags": []} for dim in DIMENSIONS
            }
            self._data["_candidate_pool"] = []

    def save(self) -> None:
        """Persist taxonomy (including candidate pool updates) to disk."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get_dimension_tags(self, dim: str) -> Set[str]:
        """Return the set of valid tags for a dimension."""
        entry = self._data.get(dim, {})
        return set(entry.get("tags", []))

    def all_tags_flat(self) -> Set[str]:
        """Return all valid tags across all dimensions."""
        result = set()
        for dim in DIMENSIONS:
            result |= self.get_dimension_tags(dim)
        return result

    def get_tags_for_prompt(self, dim: str) -> str:
        """Format dimension tags as a comma-separated string for LLM prompts."""
        tags = sorted(self.get_dimension_tags(dim))
        return ", ".join(tags)

    def map_tags(self, raw_tags: Dict[str, List[str]], skill_id: str = "") -> Dict[str, List[str]]:
        """Map LLM-generated candidate tags to the taxonomy.

        For each dimension:
          1. Exact match → accept as-is
          2. Fuzzy match (edit distance ≤ 2 or substring) → accept mapped version
          3. No match → keep with [CANDIDATE] prefix, add to candidate pool

        Returns four-dimensional tags dict. Unmatched tags are preserved with
        [CANDIDATE] marker so Stage 3 can see them for routing decisions.
        """
        mapped: Dict[str, List[str]] = {}

        for dim in DIMENSIONS:
            valid = self.get_dimension_tags(dim)
            candidates = raw_tags.get(dim, [])
            accepted = []

            for tag in candidates:
                raw_tag = tag.strip()
                tag_lower = raw_tag.lower()

                # Strip existing [CANDIDATE] prefix if present
                if tag_lower.startswith("[candidate]"):
                    tag_lower = tag_lower[len("[candidate]"):].strip()
                    raw_tag = tag_lower

                # Exact match
                if tag_lower in valid:
                    if tag_lower not in accepted:
                        accepted.append(tag_lower)
                    continue

                # Fuzzy match: substring containment
                fuzzy = self._fuzzy_match(tag_lower, valid)
                if fuzzy:
                    if fuzzy not in accepted:
                        accepted.append(fuzzy)
                    continue

                # No match → keep with [CANDIDATE] prefix, record in pool
                candidate_tag = f"[CANDIDATE] {tag_lower}"
                if candidate_tag not in accepted:
                    accepted.append(candidate_tag)
                self.add_to_candidate_pool(tag_lower, dim, skill_id)

            mapped[dim] = accepted

        return mapped

    def add_to_candidate_pool(self, tag: str, dim: str, skill_id: str = "") -> None:
        """Record an unmapped tag in the candidate pool."""
        pool = self._data.setdefault("_candidate_pool", [])

        # Check if already in pool, increment count
        for entry in pool:
            if entry["tag"] == tag and entry["dimension"] == dim:
                entry["count"] = entry.get("count", 1) + 1
                if skill_id and skill_id not in entry.get("skill_ids", []):
                    entry.setdefault("skill_ids", []).append(skill_id)
                return

        pool.append({
            "tag": tag,
            "dimension": dim,
            "count": 1,
            "skill_ids": [skill_id] if skill_id else [],
            "added_at": datetime.now().isoformat(),
        })

    def promote_candidates(self, min_count: int = 3) -> List[Dict[str, str]]:
        """Promote candidate tags that appear >= min_count times to the taxonomy.

        Returns list of promoted entries: [{"tag": ..., "dimension": ...}]
        """
        pool = self._data.get("_candidate_pool", [])
        promoted = []
        remaining = []

        for entry in pool:
            if entry.get("count", 1) >= min_count:
                dim = entry["dimension"]
                tag = entry["tag"]
                if dim in self._data and tag not in self._data[dim]["tags"]:
                    self._data[dim]["tags"].append(tag)
                    promoted.append({"tag": tag, "dimension": dim})
            else:
                remaining.append(entry)

        self._data["_candidate_pool"] = remaining
        return promoted

    @staticmethod
    def _fuzzy_match(tag: str, valid_tags: Set[str]) -> Optional[str]:
        """Try to match a tag to valid tags via substring or edit distance."""
        # Substring: tag contains a valid tag or vice versa
        for v in valid_tags:
            if v in tag or tag in v:
                return v

        # Edit distance ≤ 2
        best = None
        best_dist = 3  # threshold
        for v in valid_tags:
            d = _edit_distance(tag, v)
            if d < best_dist:
                best_dist = d
                best = v

        return best


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for j in range(1, len(b) + 1):
        curr = [j] + [0] * len(a)
        for i in range(1, len(a) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[i] = min(curr[i - 1] + 1, prev[i] + 1, prev[i - 1] + cost)
        prev = curr
    return prev[len(a)]

"""Stage 3: 分层归纳合并 (Hierarchical Consolidation).

聚合流程（自底向上）：
1. Patches → Scenarios: 按 domain 分组 + embedding 聚类 → 合并为场景文件
2. Scenarios → Domain: 从场景中抽象出领域级原则
3. Cross-domain → General: 跨领域相似原则提升为通用经验

集成预算控制：在每层写入前执行预算检查，超出时通过 LLM 合并压缩。
支持断点续传：Phase 1 的合并结果按 domain 实时保存 checkpoint。
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
import numpy as np

from ..llm import LLMClient, LocalEmbedder, cosine_similarity
from ..memory.hierarchical_store import HierarchicalStore
from . import SkillPatch


def strip_thinking_tags(text: str) -> str:
    """Remove <thinking>...</thinking> blocks from LLM response."""
    return re.sub(r'<thinking>.*?</thinking>\s*', '', text, flags=re.DOTALL).strip()


# =============================================================================
# Constants
# =============================================================================

MERGE_BATCH_SIZE = 5  # default, overridden by budget_config["merge_batch_size"]


# =============================================================================
# Prompts
# =============================================================================

MERGE_PATCHES_PROMPT = """You are merging multiple atomic skill patches that address similar problems into a single, more refined version.

## Patches to Merge
{patches_text}

---

Merge these patches into ONE consolidated entry. Rules:
- GENERALIZE: if patches describe the same insight in different words, produce one broader statement
- DEDUPLICATE: remove redundant points
- PRESERVE: keep genuinely distinct insights from each patch
- NO project-specific nouns (no file names, class names, function names)

Output ONLY the merged markdown with sections:
## Pattern Recognition
## Root Cause
## Solution Strategy"""


RESOLVE_CONFLICT_PROMPT = """Two skill patches propose contradictory actions for the same problem pattern. Resolve the conflict by examining their root causes.

## Patch A
Source PR: {pr_id_a}
Root Cause: {root_cause_a}
Content:
{content_a}

## Patch B
Source PR: {pr_id_b}
Root Cause: {root_cause_b}
Content:
{content_b}

---

Determine which patch is correct, or synthesize a resolution that accounts for both root causes.

Reply in this JSON format:
```json
{{
  "resolution": "keep_a|keep_b|synthesize",
  "rationale": "<why this resolution>",
  "merged_content": "<if synthesize, the merged markdown; otherwise empty>"
}}
```"""


GENERATE_SCENARIO_MD_PROMPT = """Generate a pattern scenario file. This file represents a cluster of similar problem cases — NOT a single PR.

## Domain: {domain}
## Pattern: {scenario_name}

## Patches Contributing to This Pattern (clustered cases)
{patches_text}

## PR Examples
{examples_text}

---

Generate the pattern file in this exact format:

## Problem Description
<What problem pattern this cluster represents. 1-2 paragraphs describing the general issue, how it manifests, and why it's hard to catch.>

## Root Cause Analysis
<The underlying structural or cognitive reason this bug class exists. What assumption or mental model leads developers to write this bug.>

## Workflow
1. <Recognition: how to identify this pattern in code>
2. <Diagnosis: how to confirm the root cause>
3. <Fix strategy: what to change>
4. <Verification: how to confirm the fix is correct>

## Boundary Cases
- <edge case or special condition 1>
- <edge case or special condition 2>
- <edge case or special condition 3>

## Examples
- <PR-id-1>: <one sentence describing how this PR exemplifies the pattern>

IMPORTANT:
- Synthesize from ALL patches in the cluster, don't just describe one case
- The Problem Description should be general enough to cover all cases in the cluster
- Workflow steps should be concrete and actionable
- Boundary Cases should highlight where the pattern is tricky or easy to miss"""


ABSTRACT_DOMAIN_PRINCIPLES_PROMPT = """You are abstracting domain-level principles from concrete scenario patterns.

## Domain: {domain}
## Description: {domain_description}

## Existing Domain Principles (if any)
{existing_principles}

## Scenario Summaries
{scenarios_text}

---

From these scenarios, abstract 3-8 domain-level principles. Each principle should:
- Apply across MULTIPLE scenarios within this domain (not just one)
- Be more abstract than any single scenario's workflow
- Be directly actionable by an AI coding agent

Output ONLY a numbered list of principles (1-8 items). Each item format:
1. **Brief title** — Direct imperative instruction (1-2 sentences, actionable, concise)

RULES:
- Output ONLY the numbered list, nothing else
- No markdown headers, no frontmatter, no pattern sections
- Imperative style (tell the agent what to do)
- Each principle must be general enough to cover multiple scenarios"""

ABSTRACT_PATTERN_SUMMARY_PROMPT = """You are summarizing a scenario pattern for the domain-level pattern index.

## Domain: {domain}
## Scenario: {scenario_name}

## Scenario Content
{scenario_content}

---

Write a 2-3 sentence summary of this pattern. Include:
1. What this pattern is (the bug category)
2. How to recognize it (key indicators)
3. The key insight (why it happens or what makes it tricky)

Output ONLY the summary text (2-3 sentences), no headers, no formatting."""


COMPRESS_SCENARIOS_PROMPT = """The following pattern scenario is being archived. Merge its key knowledge into the target pattern scenario.

## Archived Pattern
{archived_content}

## Target Pattern (merge destination)
{target_content}

Rules:
- Integrate unique knowledge from the archived pattern into the target
- Do NOT simply concatenate — synthesize and integrate
- Maintain the target's structural format
- Preserve Examples from both patterns
- If the archived pattern has boundary cases not in the target, add them

Output the complete merged pattern file content."""


# =============================================================================
# Embedding-based similarity clustering
# =============================================================================

def cluster_by_similarity(
    items: List[Dict[str, Any]],
    threshold: float = 0.8,
) -> List[List[int]]:
    """Cluster items by embedding cosine similarity.

    Returns list of clusters, each cluster is a list of item indices.
    """
    n = len(items)
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    assigned = [False] * n
    clusters = []

    for i in range(n):
        if assigned[i]:
            continue
        cluster = [i]
        assigned[i] = True
        emb_i = items[i].get("embedding", [])
        if not emb_i:
            clusters.append(cluster)
            continue
        for j in range(i + 1, n):
            if assigned[j]:
                continue
            emb_j = items[j].get("embedding", [])
            if not emb_j:
                continue
            sim = cosine_similarity(emb_i, emb_j)
            if sim >= threshold:
                cluster.append(j)
                assigned[j] = True
        clusters.append(cluster)

    return clusters


# =============================================================================
# Stage 3 Implementation
# =============================================================================

class ConsolidateStage:
    """Aggregates patch pool into three-layer hierarchical skill structure.

    Flow: patches → scenarios → domain principles → general principles
    """

    def __init__(
        self,
        llm: LLMClient,
        store: HierarchicalStore,
        embedder: LocalEmbedder,
        similarity_threshold: float = 0.8,
        budget_config: Optional[Dict[str, int]] = None,
    ):
        self.llm = llm
        self.store = store
        self.embedder = embedder
        self.similarity_threshold = similarity_threshold
        self.budget_config = budget_config or {}
        self.scenario_max = self.budget_config.get("scenario_max_per_domain", 15)
        self.domain_max_patterns = self.budget_config.get("domain_max_entries", 10)
        self.general_max = self.budget_config.get("skill_max_entries", 8)
        self.sample_ratio = self.budget_config.get("sample_ratio", 0.3)
        self.merge_batch_size = self.budget_config.get("merge_batch_size", MERGE_BATCH_SIZE)

        # Checkpoint directory for resume support
        self.checkpoint_dir = Path(self.store.skills_dir) / ".consolidate_checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    async def run(self, patches: List[SkillPatch], patch_limit: int = 0) -> Dict[str, Any]:
        """Run the full consolidation pipeline.

        If patches list is empty, loads from patch pool.
        patch_limit: max patches to process (0 = all).
        """
        report = {
            "general_count": 0,
            "domains_updated": [],
            "scenarios_count": 0,
            "duplicates_merged": 0,
            "conflicts_resolved": 0,
            "rare_cases": [],
            "errors": [],
        }

        # Load patches from pool
        all_patches = self.store.load_all_patches()
        if not all_patches:
            print("  No patches in pool, nothing to consolidate.")
            return report

        if patch_limit > 0:
            all_patches = all_patches[:patch_limit]
            print(f"  Loaded {len(all_patches)} patches from pool (limited to {patch_limit})")
        else:
            print(f"  Loaded {len(all_patches)} patches from pool")

        # Ensure all patches have embeddings
        self._ensure_embeddings(all_patches)

        # === Phase 1: Patches → Scenarios ===
        print(f"\n  [Phase 1] Aggregating patches into scenarios...")
        domain_groups = self._group_by_domain(all_patches)
        print(f"    Domains found: {list(domain_groups.keys())}")

        # Separate rare domains (only 1 patch) from substantial domains
        rare_domains = {}
        substantial_domains = {}
        for domain, domain_patches in domain_groups.items():
            if len(domain_patches) <= 1:
                rare_domains[domain] = domain_patches
            else:
                substantial_domains[domain] = domain_patches

        if rare_domains:
            print(f"    Rare cases (1 patch, skipped): {list(rare_domains.keys())}")
            self._save_rare_cases(rare_domains, report)

        for di, (domain, domain_patches) in enumerate(substantial_domains.items(), 1):
            print(f"\n    [{di}/{len(substantial_domains)}] Domain: {domain}")
            scenarios_created = await self._build_scenarios(domain, domain_patches, report)
            print(f"    → {scenarios_created} scenarios created")

        # === Phase 2: Scenarios → Domain Principles ===
        print(f"\n  [Phase 2] Abstracting domain-level principles from scenarios...")
        all_domains = list(substantial_domains.keys())
        for di, domain in enumerate(all_domains, 1):
            print(f"    [{di}/{len(all_domains)}] {domain}...", end="", flush=True)
            await self._build_domain_principles(domain, report)
            report["domains_updated"].append(domain)
            print(f" done")

        # === Phase 3: Cross-domain → General Principles ===
        print(f"\n  [Phase 3] Promoting cross-domain patterns to general principles...")
        print(f"    Analyzing {len(all_domains)} domains...", end="", flush=True)
        await self._build_general_principles(all_domains, report)
        print(f" done")

        # === Validate ===
        print(f"\n  Validating links...")
        broken_links = self.store.validate_links()
        if broken_links:
            report["errors"].extend(broken_links)
            print(f"  WARNING: {len(broken_links)} broken links")
        else:
            print(f"  All links valid")

        return report

    # =========================================================================
    # Embedding
    # =========================================================================

    def _ensure_embeddings(self, patches: List[Dict]) -> None:
        """Compute embeddings for patches that don't have them."""
        to_embed = []
        indices = []
        for i, p in enumerate(patches):
            if not p.get("embedding"):
                to_embed.append(p.get("content", ""))
                indices.append(i)

        if not to_embed:
            return

        print(f"  Computing embeddings for {len(to_embed)}/{len(patches)} patches...")
        batch_size = 128
        all_embeddings = []

        for batch_start in range(0, len(to_embed), batch_size):
            batch_end = min(batch_start + batch_size, len(to_embed))
            batch_texts = to_embed[batch_start:batch_end]
            batch_embeddings = self.embedder.embed(batch_texts)
            all_embeddings.extend(batch_embeddings)

        for j, emb in enumerate(all_embeddings):
            patches[indices[j]]["embedding"] = emb

    # =========================================================================
    # Phase 1: Patches → Scenarios
    # =========================================================================

    def _group_by_domain(self, patches: List[Dict]) -> Dict[str, List[Dict]]:
        """Group patches by their primary domain tag (stripping [CANDIDATE] prefix)."""
        groups = defaultdict(list)
        for p in patches:
            tags = p.get("tags", {})
            domains = tags.get("domain", [])
            if domains:
                primary = domains[0].replace("[CANDIDATE] ", "")
                groups[primary].append(p)
            else:
                groups["uncategorized"].append(p)
        return dict(groups)

    def _save_rare_cases(self, rare_domains: Dict[str, List[Dict]], report: Dict) -> None:
        """Save single-patch domains to a rare cases file for future reference."""
        rare_cases_path = Path(self.store.skills_dir) / "rare_cases.json"

        # Load existing rare cases
        existing = []
        if rare_cases_path.exists():
            with open(rare_cases_path, "r", encoding="utf-8") as f:
                existing = json.load(f)

        # Append new rare cases
        for domain, patches in rare_domains.items():
            for p in patches:
                entry = {
                    "domain": domain,
                    "source_pr_id": p.get("source_pr_id", "unknown"),
                    "content": p.get("content", "")[:500],
                    "tags": p.get("tags", {}),
                }
                # Avoid duplicates by source_pr_id
                if not any(e.get("source_pr_id") == entry["source_pr_id"] for e in existing):
                    existing.append(entry)

        with open(rare_cases_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        report["rare_cases"] = [d for d in rare_domains.keys()]

    async def _build_scenarios(
        self, domain: str, patches: List[Dict], report: Dict
    ) -> int:
        """Cluster patches by problem_pattern tags, sample top-k per group, merge via LLM.

        Returns number of scenarios created/updated.
        Supports checkpoint/resume: saves merged scenarios incrementally.
        No scenario count limit — one scenario per problem_pattern group.
        """
        # Load checkpoint if exists
        checkpoint_path = self.checkpoint_dir / f"{domain}.json"
        checkpoint = self._load_checkpoint(checkpoint_path)
        processed_groups = checkpoint.get("processed_groups", set())
        merged_scenarios = checkpoint.get("merged_scenarios", [])

        # Group by problem_pattern tag
        pattern_groups = defaultdict(list)
        for p in patches:
            patterns = p.get("tags", {}).get("problem_pattern", [])
            if patterns:
                pattern = patterns[0].replace("[CANDIDATE] ", "")
                pattern_groups[pattern].append(p)
            else:
                pattern_groups["uncategorized"].append(p)

        print(f"      {len(patches)} patches → {len(pattern_groups)} raw problem_pattern groups")

        # Merge similar pattern groups by tag name embedding similarity
        pattern_groups = self._merge_similar_pattern_groups(pattern_groups)
        print(f"      After tag-level merge: {len(pattern_groups)} groups")

        # Process each group
        total_groups = len(pattern_groups)
        pending_groups = [p for p in pattern_groups if p not in processed_groups]
        print(f"      Progress: {len(processed_groups)}/{total_groups} groups done, {len(pending_groups)} pending")

        for idx, pattern in enumerate(pending_groups, len(processed_groups) + 1):
            group_patches = pattern_groups[pattern]

            # Sample top percentage of patches closest to centroid
            sampled = self._sample_by_ratio(group_patches, self.sample_ratio)

            # Skip LLM merge if only 1 patch — use it directly
            if len(sampled) == 1:
                print(f"      [{idx}/{total_groups}] {pattern}: {len(group_patches)} patches → 1 sampled → skip merge")
                merged_scenarios.append(sampled[0])
            else:
                progress_prefix = f"      [{idx}/{total_groups}] {pattern}: {len(group_patches)}→{len(sampled)} merging"
                print(f"{progress_prefix}...", end="", flush=True)
                report["duplicates_merged"] += len(sampled) - 1
                merged = await self._merge_cluster(sampled, progress_prefix)
                merged_scenarios.append(merged)
                print(f" done")

            # Save checkpoint after each scenario merge (includes processed ids + results)
            processed_groups.add(pattern)
            self._save_checkpoint(checkpoint_path, {
                "processed_groups": list(processed_groups),
                "merged_scenarios": merged_scenarios,
            })
            print(f"        checkpoint saved ({idx}/{total_groups})")

        # Budget control: compress if exceeding scenario_max_per_domain
        if len(merged_scenarios) > self.scenario_max:
            print(f"      Budget exceeded: {len(merged_scenarios)} scenarios > max {self.scenario_max}, compressing...")
            merged_scenarios = await self._compress_to_budget(
                merged_scenarios, self.scenario_max, domain, report
            )
            print(f"      Compressed to {len(merged_scenarios)} scenarios")

        # Write scenario files
        for i, merged in enumerate(merged_scenarios):
            scenario_name = self._generate_scenario_name(merged, domain, i)
            await self._write_scenario_md(domain, scenario_name, merged)
            report["scenarios_count"] += 1

        # Clear checkpoint after successful completion
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            print(f"      Checkpoint cleared for {domain}")

        return len(merged_scenarios)

    async def _compress_to_budget(
        self, clusters: List[Dict], max_count: int, domain: str, report: Dict
    ) -> List[Dict]:
        """Reduce clusters to max_count by merging the most similar pairs."""
        total_merges = len(clusters) - max_count
        merge_count = 0
        while len(clusters) > max_count:
            # Find the most similar pair
            best_sim = -1.0
            best_i, best_j = 0, 1
            for i in range(len(clusters)):
                emb_i = clusters[i].get("embedding", [])
                if not emb_i:
                    continue
                for j in range(i + 1, len(clusters)):
                    emb_j = clusters[j].get("embedding", [])
                    if not emb_j:
                        continue
                    sim = cosine_similarity(emb_i, emb_j)
                    if sim > best_sim:
                        best_sim = sim
                        best_i, best_j = i, j

            # Merge the most similar pair
            merge_count += 1
            print(f"        compressing {merge_count}/{total_merges} (sim={best_sim:.3f})", end="\r", flush=True)
            merged = await self._merge_cluster([clusters[best_i], clusters[best_j]])
            clusters = [c for idx, c in enumerate(clusters) if idx not in (best_i, best_j)]
            clusters.append(merged)
            report["duplicates_merged"] += 1

        if total_merges > 0:
            print()
        return clusters

    def _sample_by_ratio(self, patches: List[Dict], ratio: float) -> List[Dict]:
        """Sample patches closest to the centroid embedding.

        Adaptive sampling:
        - Small groups (<=5): return all patches (no sampling)
        - Medium groups (6-15): sample at least 5
        - Large groups (>15): sample by configured ratio
        """
        import math

        n = len(patches)
        if n <= 5:
            return patches

        if n <= 15:
            k = min(n, 5 + math.ceil(n * ratio))
        else:
            k = max(5, math.ceil(n * ratio))

        if k >= n:
            return patches

        # Compute centroid
        embeddings = [p.get("embedding", []) for p in patches]
        valid_embeddings = [e for e in embeddings if e]
        if not valid_embeddings:
            return patches[:k]

        centroid = np.mean(valid_embeddings, axis=0)

        # Compute distances to centroid
        distances = []
        for i, p in enumerate(patches):
            emb = p.get("embedding", [])
            if emb:
                sim = cosine_similarity(emb, centroid.tolist())
                distances.append((1 - sim, i))
            else:
                distances.append((999, i))

        # Sort by distance and take top-k
        distances.sort()
        topk_indices = [idx for _, idx in distances[:k]]
        return [patches[i] for i in topk_indices]

    def _merge_similar_pattern_groups(
        self, pattern_groups: Dict[str, List[Dict]], threshold: float = 0.65
    ) -> Dict[str, List[Dict]]:
        """Merge pattern groups whose tag names are semantically similar.

        Uses embedding similarity on the tag name strings themselves.
        Groups with similar names (e.g. 'copy-paste-identity-residue' and
        'copy-paste-identity-error') get merged under the largest group's name.
        """
        names = list(pattern_groups.keys())
        if len(names) <= 1:
            return dict(pattern_groups)

        # Embed all tag names
        name_embeddings = self.embedder.embed(names)

        # Greedy clustering on tag name embeddings
        n = len(names)
        assigned = [False] * n
        clusters = []  # each cluster: list of indices

        # Sort by group size descending so larger groups become cluster centers
        size_order = sorted(range(n), key=lambda i: len(pattern_groups[names[i]]), reverse=True)

        for i in size_order:
            if assigned[i]:
                continue
            cluster = [i]
            assigned[i] = True
            emb_i = name_embeddings[i]
            for j in size_order:
                if assigned[j]:
                    continue
                emb_j = name_embeddings[j]
                sim = cosine_similarity(emb_i, emb_j)
                if sim >= threshold:
                    cluster.append(j)
                    assigned[j] = True
            clusters.append(cluster)

        # Build merged groups: use the largest group's name as the key
        merged = {}
        for cluster in clusters:
            primary_idx = cluster[0]  # already sorted by size, first is largest
            primary_name = names[primary_idx]
            all_patches = []
            for idx in cluster:
                all_patches.extend(pattern_groups[names[idx]])
            merged[primary_name] = all_patches

        return merged

    def _generate_scenario_name(self, merged_patch: Dict, domain: str, index: int) -> str:
        """Generate a kebab-case scenario name from patch content."""
        content = merged_patch.get("content", "")
        tags = merged_patch.get("tags", {})
        patterns = tags.get("problem_pattern", [])

        if patterns:
            name = patterns[0].replace("[CANDIDATE] ", "")
            name = re.sub(r'[^a-z0-9-]', '-', name.lower())
            name = re.sub(r'-+', '-', name).strip('-')
            if name:
                return name

        # Fallback: extract from content first line
        first_line = content.split('\n')[0] if content else ""
        words = re.findall(r'[a-z]+', first_line.lower())
        if len(words) >= 2:
            return '-'.join(words[:4])

        return f"pattern-{index + 1}"

    # =========================================================================
    # Phase 2: Scenarios → Domain Principles
    # =========================================================================

    async def _build_domain_principles(self, domain: str, report: Dict) -> None:
        """Abstract domain-level principles from existing scenarios and assemble domain.md."""
        scenarios = self.store.list_scenarios(domain)
        if not scenarios:
            return

        # Step 1: Generate domain-level principles via LLM
        scenarios_text = ""
        for s in scenarios:
            content = self.store.read_scenario_md(domain, s)
            desc_match = re.search(r'## Problem Description\s*\n(.*?)(?=## |\Z)', content, re.DOTALL)
            desc = desc_match.group(1).strip()[:500] if desc_match else s
            scenarios_text += f"\n### {s}\n{desc}\n"

        existing = self.store.read_domain_md(domain)
        existing_principles = ""
        if existing:
            principles_match = re.search(r'## (?:Principles|Domain Principles|解决思路)\s*\n(.*?)(?=\n## |\Z)', existing, re.DOTALL)
            existing_principles = principles_match.group(1).strip() if principles_match else ""

        domain_description = f"Bugs caused by {domain.replace('-', ' ')} issues"

        prompt = ABSTRACT_DOMAIN_PRINCIPLES_PROMPT.format(
            domain=domain,
            domain_description=domain_description,
            existing_principles=existing_principles or "(none yet)",
            scenarios_text=scenarios_text,
        )

        principles_response = await self.llm.chat([
            {"role": "system", "content": "You are a domain knowledge architect. Output only the numbered list."},
            {"role": "user", "content": prompt},
        ])
        principles_text = strip_thinking_tags(principles_response).strip()

        # Step 2: Generate pattern summaries (one per scenario)
        pattern_sections = []
        for scenario_name in scenarios:
            content = self.store.read_scenario_md(domain, scenario_name)

            # Extract scenario title from first line or use filename
            title_match = re.search(r'^#\s+Pattern:\s+(.+?)(?:\s+\(|$)', content, re.MULTILINE)
            pattern_title = title_match.group(1) if title_match else scenario_name.replace('-', ' ').title()

            # Generate pattern summary via LLM
            summary_prompt = ABSTRACT_PATTERN_SUMMARY_PROMPT.format(
                domain=domain,
                scenario_name=scenario_name,
                scenario_content=content[:1500],  # First 1500 chars for context
            )

            summary_response = await self.llm.chat([
                {"role": "system", "content": "You are summarizing a bug pattern. Output only the summary text."},
                {"role": "user", "content": summary_prompt},
            ])
            summary = strip_thinking_tags(summary_response).strip()

            pattern_sections.append(f"### {pattern_title}\n{summary}\n→ 详见 [{scenario_name}.md](./{domain}/scenarios/{scenario_name}.md)")

        patterns_text = "\n\n".join(pattern_sections)

        # Step 3: Build scenario reference index (programmatically)
        scenario_refs = []
        for scenario_name in scenarios:
            content = self.store.read_scenario_md(domain, scenario_name)
            # Extract one-line description from Problem Description
            desc_match = re.search(r'## Problem Description\s*\n(.*?)(?:\.|$)', content, re.DOTALL)
            if desc_match:
                one_liner = desc_match.group(1).strip().split('\n')[0][:120]
            else:
                one_liner = f"Scenario: {scenario_name}"
            scenario_refs.append(f"- [{scenario_name}](./{domain}/scenarios/{scenario_name}.md) — {one_liner}")

        scenario_ref_text = "\n".join(scenario_refs)

        # Step 4: Assemble domain.md programmatically
        domain_md_content = f"""---
name: {domain}
description: {domain_description}
---

## Principles

{principles_text}

## Patterns

{patterns_text}

## Scenario Reference
{scenario_ref_text}
"""

        self.store.write_domain_md(domain, domain_md_content.strip())

    # =========================================================================
    # Phase 3: Cross-domain → General Principles
    # =========================================================================

    def _extract_domain_principles(self, all_domains: List[str]) -> List[Dict[str, Any]]:
        """Extract individual principles from all domain.md files.

        Returns list of {"domain": str, "principle_text": str} dicts.
        """
        principles = []
        for domain in all_domains:
            content = self.store.read_domain_md(domain)
            if not content:
                continue

            # Extract principles section (may be "## Principles" or "## 解决思路")
            match = re.search(r'## (?:Principles|Domain Principles|解决思路)\s*\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
            if not match:
                continue

            section = match.group(1).strip()

            # Split by numbered items (e.g., "1. ", "2. ")
            items = re.split(r'\n(?=\d+\.\s)', section)
            for item in items:
                item = item.strip()
                if not item:
                    continue
                # Remove leading number
                principle_text = re.sub(r'^\d+\.\s*', '', item).strip()
                if principle_text:
                    principles.append({
                        "domain": domain,
                        "principle_text": principle_text,
                    })

        return principles

    def _cluster_cross_domain_principles(
        self, principles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Cluster principles by similarity across domains with centroid refinement.

        Returns list of clusters: [{"domains_set": set, "principles": list, "recurrence_count": int, "centroid": list}]
        """
        if not principles:
            return []

        # Use a lower threshold for cross-domain clustering (0.7 instead of 0.8)
        # because principles from different domains may have different wording
        cross_domain_threshold = max(0.7, self.similarity_threshold - 0.1)

        # Step 1: Build adjacency graph (only connect principles from different domains)
        n = len(principles)
        adjacency = [set() for _ in range(n)]
        edge_count = 0

        for i in range(n):
            emb_i = principles[i].get("embedding", [])
            if not emb_i:
                continue
            for j in range(i + 1, n):
                # Only connect if from different domains
                if principles[i]["domain"] == principles[j]["domain"]:
                    continue

                emb_j = principles[j].get("embedding", [])
                if not emb_j:
                    continue

                sim = cosine_similarity(emb_i, emb_j)
                if sim >= cross_domain_threshold:
                    adjacency[i].add(j)
                    adjacency[j].add(i)
                    edge_count += 1

        print(f"      Cross-domain edges found: {edge_count} (threshold={cross_domain_threshold:.2f})")

        # Step 2: Extract connected components (DFS)
        visited = [False] * n
        components = []

        def dfs(node, component):
            visited[node] = True
            component.append(node)
            for neighbor in adjacency[node]:
                if not visited[neighbor]:
                    dfs(neighbor, component)

        for i in range(n):
            if not visited[i]:
                component = []
                dfs(i, component)
                if len(component) > 0:
                    components.append(component)

        print(f"      Connected components: {len(components)}")

        # Step 3: Centroid-based refinement for each component
        clusters = []
        for component_indices in components:
            # Get principles in this component
            component_principles = [principles[i] for i in component_indices]

            # Compute centroid
            embeddings = [p["embedding"] for p in component_principles if p.get("embedding")]
            if not embeddings:
                continue

            centroid = np.mean(embeddings, axis=0).tolist()

            # Filter: keep only principles close to centroid
            filtered_principles = []
            for p in component_principles:
                if not p.get("embedding"):
                    continue
                sim_to_centroid = cosine_similarity(p["embedding"], centroid)
                if sim_to_centroid >= cross_domain_threshold:
                    filtered_principles.append(p)

            if not filtered_principles:
                continue

            # Compute domains_set and recurrence_count
            domains_set = set(p["domain"] for p in filtered_principles)
            recurrence_count = len(domains_set)

            clusters.append({
                "domains_set": domains_set,
                "principles": filtered_principles,
                "recurrence_count": recurrence_count,
                "centroid": centroid,
            })

        return clusters

    async def _abstract_principle_cluster(
        self, cluster: Dict[str, Any], principle_number: int
    ) -> str:
        """Abstract a cluster of similar principles into one universal principle.

        Returns formatted principle text: "### N. Title\nBody"
        """
        domains_list = ", ".join(sorted(cluster["domains_set"]))
        principles_text = ""
        for i, p in enumerate(cluster["principles"], 1):
            principles_text += f"{i}. [{p['domain']}] {p['principle_text']}\n"

        prompt = f"""You are abstracting a universal coding principle from similar patterns across multiple domains.

## Domains Represented
{domains_list}

## Similar Principles
{principles_text.strip()}

Generate ONE highly abstracted, universal principle that captures the essence of all these patterns.

Format:
### {principle_number}. <Short Title>
<Direct imperative instruction, 1-3 sentences. Imperative, concise, actionable.>

RULES:
- Must apply to ANY language/framework
- Imperative style (tell the agent what to do)
- No implementation details
- Output ONLY the formatted principle (### line + body), nothing else"""

        response = await self.llm.chat([
            {"role": "system", "content": "You are a coding principle architect. Output only the formatted principle."},
            {"role": "user", "content": prompt},
        ])

        return strip_thinking_tags(response).strip()

    async def _build_general_principles(self, all_domains: List[str], report: Dict) -> None:
        """Find cross-domain patterns via embedding clustering and generate SKILL.md."""
        if not all_domains:
            return

        # Step 1: Extract individual principles from all domain.md files
        principles = self._extract_domain_principles(all_domains)

        cross_domain_clusters = []
        if principles:
            print(f"    Phase 3: Extracted {len(principles)} principles from {len(all_domains)} domains")

            # Step 2: Embed all principles
            texts = [p["principle_text"] for p in principles]
            embeddings = self.embedder.embed(texts)
            for i, emb in enumerate(embeddings):
                principles[i]["embedding"] = emb

            # Step 3: Cluster by cross-domain similarity with centroid refinement
            clusters = self._cluster_cross_domain_principles(principles)

            # Step 4: Filter clusters with recurrence >= 2, sort by recurrence descending
            cross_domain_clusters = [c for c in clusters if c["recurrence_count"] >= 2]
            cross_domain_clusters.sort(key=lambda c: c["recurrence_count"], reverse=True)
        else:
            print(f"    Phase 3: No principles extracted from domain files")

        print(f"    Phase 3: {len(cross_domain_clusters)} cross-domain clusters (recurrence >= 2)")

        # Step 5: Abstract each cluster into one core principle via LLM
        core_principles_text = ""
        if cross_domain_clusters:
            selected = cross_domain_clusters[:self.general_max]
            for i, cluster in enumerate(selected, 1):
                domains_str = ", ".join(sorted(cluster["domains_set"]))
                print(f"      [{i}/{len(selected)}] Abstracting principle (recurrence={cluster['recurrence_count']}, domains: {domains_str})...")
                principle_text = await self._abstract_principle_cluster(cluster, i)
                core_principles_text += principle_text + "\n\n"
            report["general_count"] = len(selected)
        else:
            report["general_count"] = 0

        # Step 6: Assemble SKILL.md programmatically (always generate, even without core principles)
        domain_index_lines = []
        for domain in sorted(all_domains):
            desc = self._get_domain_description(domain)
            domain_index_lines.append(f"- [{domain}](references/{domain}.md) — {desc}")
        domain_index = "\n".join(domain_index_lines)

        core_section = core_principles_text.strip()
        if not core_section:
            core_section = ""

        skill_md_content = f"""---
name: coding-master
description: use this skill when you are solving coding task.
---

## Core Principles

{core_section}

## domain

{domain_index}
"""

        self.store.write_skill_md(skill_md_content.strip())

    def _get_domain_description(self, domain: str) -> str:
        """Extract the description from a domain.md frontmatter."""
        content = self.store.read_domain_md(domain)
        if not content:
            return f"Bugs related to {domain.replace('-', ' ')}"
        match = re.search(r'^---\s*\n.*?description:\s*(.+?)\n.*?---', content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return f"Bugs related to {domain.replace('-', ' ')}"

    # =========================================================================
    # Merge & Conflict Resolution
    # =========================================================================

    async def _merge_cluster(self, cluster: List[Dict], progress_prefix: str = "") -> Dict:
        """Merge a cluster of similar patches using hierarchical reduce-tree."""
        if len(cluster) == 1:
            return cluster[0]

        if len(cluster) <= self.merge_batch_size:
            return await self._merge_batch(cluster)

        batches = [
            cluster[i:i + self.merge_batch_size]
            for i in range(0, len(cluster), self.merge_batch_size)
        ]
        merged_batches = []
        for i, batch in enumerate(batches, 1):
            if progress_prefix:
                print(f"\r{progress_prefix} batch {i}/{len(batches)}", end="", flush=True)
            merged = await self._merge_batch(batch)
            merged_batches.append(merged)

        return await self._merge_cluster(merged_batches, progress_prefix)

    async def _merge_batch(self, batch: List[Dict]) -> Dict:
        """Merge a small batch (≤ MERGE_BATCH_SIZE) of patches via LLM."""
        if len(batch) == 1:
            return batch[0]

        patches_text = ""
        for i, p in enumerate(batch):
            patches_text += f"\n### Patch {i+1} (from PR: {p.get('source_pr_id', '?')})\n"
            patches_text += p.get("content", "(empty)") + "\n"

        prompt = MERGE_PATCHES_PROMPT.format(patches_text=patches_text)
        response = await self.llm.chat([
            {"role": "system", "content": "You are a knowledge consolidation expert. Output only markdown."},
            {"role": "user", "content": prompt},
        ])

        merged = dict(batch[0])
        merged["content"] = response.strip()

        # Union all tags
        all_tags = {"domain": set(), "problem_pattern": set()}
        for p in batch:
            for dim, tags in p.get("tags", {}).items():
                if dim in all_tags:
                    all_tags[dim].update(tags)
        merged["tags"] = {dim: list(tags) for dim, tags in all_tags.items()}

        # Track all source PRs
        all_pr_ids = set()
        for p in batch:
            pr_id = p.get("source_pr_id", "")
            if pr_id:
                all_pr_ids.add(pr_id)
            for existing_id in p.get("merged_source_pr_ids", []):
                all_pr_ids.add(existing_id)
        merged["merged_source_pr_ids"] = list(all_pr_ids)

        # Recompute embedding for merged content
        merged["embedding"] = self.embedder.embed_single(merged["content"])

        return merged

    async def _resolve_conflict(self, patch_a: Dict, patch_b: Dict) -> Dict:
        """Resolve conflicting patches via LLM arbitration."""
        prompt = RESOLVE_CONFLICT_PROMPT.format(
            pr_id_a=patch_a.get("source_pr_id", "?"),
            root_cause_a=patch_a.get("root_cause", ""),
            content_a=patch_a.get("content", ""),
            pr_id_b=patch_b.get("source_pr_id", "?"),
            root_cause_b=patch_b.get("root_cause", ""),
            content_b=patch_b.get("content", ""),
        )
        response = await self.llm.chat([
            {"role": "system", "content": "You are a conflict resolution expert. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ])
        parsed = self._extract_json(response)
        resolution = parsed.get("resolution", "keep_a")
        if resolution == "keep_b":
            return patch_b
        elif resolution == "synthesize" and parsed.get("merged_content"):
            merged = dict(patch_a)
            merged["content"] = parsed["merged_content"]
            return merged
        return patch_a

    # =========================================================================
    # File Writers
    # =========================================================================

    async def _write_scenario_md(self, domain: str, scenario_name: str,
                                  merged_patch: Dict) -> None:
        """Write a scenario file from a merged patch cluster."""
        patches_text = merged_patch.get("content", "")

        # Collect PR examples
        examples = []
        pr_id = merged_patch.get("source_pr_id", "")
        if pr_id:
            examples.append(f"- {pr_id}")
        for existing_id in merged_patch.get("merged_source_pr_ids", []):
            if existing_id and f"- {existing_id}" not in examples:
                examples.append(f"- {existing_id}")
        examples_text = "\n".join(examples) if examples else "(none)"

        prompt = GENERATE_SCENARIO_MD_PROMPT.format(
            domain=domain,
            scenario_name=scenario_name,
            patches_text=patches_text,
            examples_text=examples_text,
        )
        response = await self.llm.chat([
            {"role": "system", "content": "You are a scenario documentation expert. Output only markdown."},
            {"role": "user", "content": prompt},
        ])
        self.store.write_scenario_md(domain, scenario_name, strip_thinking_tags(response))

    # =========================================================================
    # Checkpoint helpers
    # =========================================================================

    def _get_patch_id(self, patch: Dict) -> str:
        """Generate unique ID for a patch."""
        pr_id = patch.get("source_pr_id", "unknown")
        dim = patch.get("dimension_label", "main")
        return f"{pr_id}__{dim}"

    def _load_checkpoint(self, checkpoint_path: Path) -> Dict:
        """Load checkpoint if exists, otherwise return empty state."""
        if not checkpoint_path.exists():
            return {"processed_groups": set(), "merged_scenarios": []}

        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Convert list back to set
            data["processed_groups"] = set(data.get("processed_groups", []))
            # Backward compat: old format used processed_patch_ids
            if "processed_patch_ids" in data and "processed_groups" not in data:
                data["processed_groups"] = set()
                data["merged_scenarios"] = data.get("merged_clusters", [])
            if "merged_scenarios" not in data:
                data["merged_scenarios"] = data.get("merged_clusters", [])
            return data
        except (json.JSONDecodeError, IOError):
            return {"processed_groups": set(), "merged_scenarios": []}

    def _save_checkpoint(self, checkpoint_path: Path, state: Dict) -> None:
        """Save checkpoint state."""
        save_state = dict(state)
        # Convert sets to lists for JSON serialization
        for key in ("processed_groups", "processed_patch_ids"):
            if isinstance(save_state.get(key), set):
                save_state[key] = list(save_state[key])

        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(save_state, f, ensure_ascii=False, indent=2)

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _format_patches_for_prompt(patches: List[Dict]) -> str:
        text = ""
        for i, p in enumerate(patches):
            text += f"\n### Patch {i+1} (PR: {p.get('source_pr_id', '?')})\n"
            tags = p.get("tags", {})
            text += f"Tags: {json.dumps(tags, ensure_ascii=False)}\n"
            text += p.get("content", "(empty)") + "\n"
        return text

    @staticmethod
    def _extract_json(response: str) -> Dict[str, Any]:
        match = re.search(r'```json\s*\n(.*?)\n\s*```', response, re.DOTALL)
        text = match.group(1) if match else response.strip()
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

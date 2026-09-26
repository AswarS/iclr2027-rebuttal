"""Three-stage pipeline runner.

Stage 1: PR 语义解构 (Decompose)     — PR → PRInstance → Dimensions
Stage 2: 原子技能补丁化 (Patch Gen)  — Dimensions → SkillPatches (validated)
Stage 3: 分层归纳合并 (Consolidate)  — Patch Pool → 三层分层存储
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Set

from .llm import create_llm_client, LLMClient, LocalEmbedder
from .memory.hierarchical_store import HierarchicalStore
from .pr_parser import PRData, load_dataset
from .taxonomy import Taxonomy
from .stages import DecomposeStage, PatchGenStage, ConsolidateStage, SkillPatch


class PRStudyRunner:
    """Orchestrates the three-stage PR → Skill pipeline."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.llm = create_llm_client(config.get("llm", {}))

        study_cfg = config.get("study", {})
        self.dataset_path = study_cfg.get("dataset_path", "data/input.jsonl")
        self.similarity_threshold = study_cfg.get("similarity_threshold", 0.8)
        self.selected_ids_path = study_cfg.get("selected_ids_path", None)
        self.concurrency = study_cfg.get("concurrency", 1)
        self.consolidate_limit = study_cfg.get("consolidate_limit", 0)

        # Storage
        self.store = HierarchicalStore(
            skills_dir=study_cfg.get("skills_path", "data/skills"),
            patch_pool_dir=study_cfg.get("patch_pool_path", "data/skills/patch_pool"),
        )

        # Taxonomy
        self.taxonomy = Taxonomy(
            study_cfg.get("taxonomy_path", "config/taxonomy.json")
        )

        # Logging
        self.log_path = Path(study_cfg.get("log_path", "data/study_logs"))
        self.log_path.mkdir(parents=True, exist_ok=True)

        # Stages
        embedder = LocalEmbedder("all-MiniLM-L12-v2")
        self.stage1 = DecomposeStage(self.llm)
        self.stage2 = PatchGenStage(self.llm, embedder)
        budget_config = study_cfg.get("budget", {})
        self.stage3 = ConsolidateStage(
            llm=self.llm,
            store=self.store,
            embedder=embedder,
            similarity_threshold=self.similarity_threshold,
            budget_config=budget_config,
        )

    def _save_log(self, instance_id: str, data: Dict[str, Any]) -> None:
        """Save study log for a single PR."""
        log_file = self.log_path / f"{instance_id.replace('/', '__')}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _get_processed_prs(self) -> Set[str]:
        """Get set of already-processed PR instance IDs from log files."""
        done = set()
        if self.log_path.exists():
            for log_file in self.log_path.glob("*.json"):
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("status") == "success":
                        done.add(data.get("instance_id", ""))
                except (json.JSONDecodeError, KeyError):
                    pass
        return done

    async def process_one_pr(self, pr: PRData) -> Dict[str, Any]:
        """Process a single PR through Stage 1 + Stage 2.

        Returns log data dict. Stage 3 (consolidation) runs separately.
        """
        log_data = {"instance_id": pr.instance_id, "repo": pr.repo}

        # === Stage 1: 语义解构 ===
        print(f"  [Stage 1] Decomposing PR...")
        instance, dimensions = await self.stage1.run(pr)
        print(f"    Intent: {instance.intent[:80]}")
        print(f"    Actions: {len(instance.actions)}")
        print(f"    Dimensions: {len(dimensions)} — {[d['label'] for d in dimensions]}")
        log_data["instance"] = instance.to_dict()
        log_data["dimensions"] = len(dimensions)

        # === Stage 2: 补丁生成 + 验证 ===
        print(f"  [Stage 2] Generating skill patches...")
        patches = await self.stage2.run(pr, instance, dimensions, self.taxonomy)

        patch_results = []
        for patch in patches:
            # Save to patch pool
            patch_path = self.store.save_patch(patch.to_dict())
            domain_tags = patch.tags.get("domain", [])
            print(f"    → Patch [{patch.dimension_label}]: "
                  f"domain={domain_tags}, "
                  f"validated={patch.validated}, "
                  f"confidence={patch.confidence_score:.2f}")
            patch_results.append({
                "dimension_label": patch.dimension_label,
                "validated": patch.validated,
                "confidence_score": patch.confidence_score,
                "tags": patch.tags,
                "path": patch_path,
            })

        log_data["patches"] = patch_results
        log_data["status"] = "success"
        return log_data

    async def _safe_process(self, pr: PRData) -> Dict[str, Any]:
        """Process a single PR with error handling."""
        try:
            return await self.process_one_pr(pr)
        except Exception as e:
            print(f"  [ERROR] {e}")
            import traceback
            traceback.print_exc()
            return {
                "instance_id": pr.instance_id,
                "repo": pr.repo,
                "status": "error",
                "error": str(e),
            }

    async def run(
        self,
        limit: int = 0,
        start_from: Optional[str] = None,
        consolidate_only: bool = False,
        validate_only: bool = False,
    ) -> None:
        """Run the pipeline.

        Args:
            limit: Max PRs to process (0 = all)
            start_from: Start from this instance_id
            consolidate_only: Skip Stage 1+2, only run Stage 3
            validate_only: Only validate existing output
        """
        # === Validate-only mode ===
        if validate_only:
            print("Validating output structure...")
            broken = self.store.validate_links()
            if broken:
                print(f"Found {len(broken)} broken links:")
                for b in broken:
                    print(f"  {b}")
            else:
                print("All links valid.")
            return

        # === Consolidate-only mode ===
        if consolidate_only:
            await self._run_consolidation()
            return

        # === Full pipeline: Stage 1 + 2 per PR, then Stage 3 ===
        print(f"Loading dataset: {self.dataset_path}")
        prs = load_dataset(self.dataset_path)
        print(f"Total PRs: {len(prs)}")

        # Filter by clustering selection if provided
        if self.selected_ids_path:
            from .clustering import ClusterResult
            cluster_result = ClusterResult.load(self.selected_ids_path)
            selected_set = set(cluster_result.selected_ids)
            prs = [pr for pr in prs if pr.instance_id in selected_set]
            print(f"Filtered by clustering: {len(prs)} selected PRs")

        done = self._get_processed_prs()
        print(f"Already processed: {len(done)} PRs")

        # Filter to pending PRs
        started = start_from is None
        pending: List[PRData] = []
        for pr in prs:
            if not started:
                if pr.instance_id == start_from:
                    started = True
                else:
                    continue
            if pr.instance_id in done:
                continue
            pending.append(pr)
            if limit > 0 and len(pending) >= limit:
                break

        if not pending:
            print("No new PRs to process.")
        elif self.concurrency <= 1:
            # Serial mode
            patch_count = 0
            for idx, pr in enumerate(pending, 1):
                print(f"\n{'='*60}")
                print(f"[{idx}/{len(pending)}] {pr.instance_id}")
                print(f"  Repo: {pr.repo}")
                print(f"  Files: {', '.join(pr.changed_files[:5])}")
                log_data = await self._safe_process(pr)
                patch_count += len(log_data.get("patches", []))
                self._save_log(pr.instance_id, log_data)
            print(f"\n{'='*60}")
            print(f"Stage 1+2 complete: processed {len(pending)} PRs, generated {patch_count} patches")
        else:
            # Parallel mode
            print(f"Parallel mode: concurrency={self.concurrency}")
            semaphore = asyncio.Semaphore(self.concurrency)
            counter = {"done": 0, "patches": 0}

            async def _worker(pr: PRData) -> None:
                async with semaphore:
                    counter["done"] += 1
                    idx = counter["done"]
                    print(f"\n{'='*60}")
                    print(f"[{idx}/{len(pending)}] {pr.instance_id}")
                    print(f"  Repo: {pr.repo}")
                    print(f"  Files: {', '.join(pr.changed_files[:5])}")
                    log_data = await self._safe_process(pr)
                    counter["patches"] += len(log_data.get("patches", []))
                    self._save_log(pr.instance_id, log_data)

            await asyncio.gather(*[_worker(pr) for pr in pending])
            print(f"\n{'='*60}")
            print(f"Stage 1+2 complete: processed {len(pending)} PRs, generated {counter['patches']} patches")

        # Persist taxonomy candidate pool after all PRs
        if pending:
            self.taxonomy.save()

        # === Stage 3: Consolidation ===
        if pending:
            await self._run_consolidation()

        # Promote candidate tags
        promoted = self.taxonomy.promote_candidates(min_count=3)
        if promoted:
            self.taxonomy.save()
            print(f"Promoted {len(promoted)} candidate tags:")
            for p in promoted:
                print(f"  [{p['dimension']}] {p['tag']}")

    async def _run_consolidation(self) -> None:
        """Run Stage 3: load all patches and consolidate into three-layer structure."""
        print(f"\n{'='*60}")
        print("[Stage 3] Consolidating patches into hierarchical structure...")

        # Stage 3 will load patches from pool itself, pass empty list
        report = await self.stage3.run([], patch_limit=self.consolidate_limit)

        print(f"\n  Consolidation report:")
        print(f"    General principles: {report.get('general_count', 0)}")
        print(f"    Domains updated: {report.get('domains_updated', [])}")
        print(f"    Scenarios created/updated: {report.get('scenarios_count', 0)}")
        print(f"    Duplicates merged: {report.get('duplicates_merged', 0)}")
        print(f"    Conflicts resolved: {report.get('conflicts_resolved', 0)}")

        # Validate
        broken = self.store.validate_links()
        if broken:
            print(f"  WARNING: {len(broken)} broken links after consolidation:")
            for b in broken:
                print(f"    {b}")
        else:
            print("  All links valid.")

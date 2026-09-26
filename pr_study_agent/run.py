#!/usr/bin/env python
"""
PR Study Agent — 三阶段流水线：从 PR 中提取声明式技能知识。

用法:
    python run.py --limit 1              # 处理 1 个 PR (Stage 1+2)
    python run.py --limit 10             # 处理 10 个 PR (Stage 1+2)
    python run.py                        # 处理所有 PR (Stage 1+2)
    python run.py --consolidate-only     # 仅运行 Stage 3 (归纳合并)
    python run.py --validate             # 校验输出结构和链接
    python run.py --full                 # 完整流水线 (Stage 1+2+3)

输出:
    data/skills/SKILL.md                              # 第一层：总纲领
    data/skills/references/[domain].md                # 第二层：领域知识
    data/skills/references/[domain]/scenarios/*.md    # 第三层：具体场景
    data/skills/patch_pool/*.json                     # 中间产物：skill patches
    data/study_logs/*.json                            # 每个 PR 的处理日志
"""

import asyncio
import argparse
import sys
from pathlib import Path

import yaml


def load_config(config_path: str) -> dict:
    """Load YAML config."""
    path = Path(config_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def parse_args():
    parser = argparse.ArgumentParser(
        description="PR Study Agent — 三阶段流水线：PR → Skill Patches → 分层知识库"
    )
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径（默认 config/config.yaml）")
    parser.add_argument("--dataset", type=str, default=None,
                        help="覆盖数据集路径 (支持 .jsonl 和 .parquet)")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多处理 N 个 PR（0=全部）")
    parser.add_argument("--start-from", type=str, default=None,
                        help="从指定 instance_id 开始")
    parser.add_argument("--consolidate-only", action="store_true",
                        help="仅运行 Stage 3 归纳合并（跳过 Stage 1+2）")
    parser.add_argument("--validate", action="store_true",
                        help="校验输出结构和 Markdown 链接")
    parser.add_argument("--full", action="store_true",
                        help="完整流水线：Stage 1+2 处理所有 PR 后自动运行 Stage 3")
    parser.add_argument("--selected", type=str, default=None,
                        help="聚类结果文件路径，仅处理其中 selected_ids 列出的 PR")
    parser.add_argument("--concurrency", type=int, default=None,
                        help="Stage 1+2 并行处理 PR 数（默认 1，即串行）")
    parser.add_argument("--consolidate-limit", type=int, default=0,
                        help="Stage 3 最多聚合 N 个 patches（0=全部，用于测试大数据集）")
    return parser.parse_args()


async def main():
    args = parse_args()

    # Project root = directory containing this script
    project_root = Path(__file__).parent.resolve()

    # Load config
    config_path = args.config or str(project_root / "config" / "config.yaml")
    config = load_config(config_path)

    # Resolve relative paths in config relative to project root
    study_cfg = config.setdefault("study", {})
    for key in ["dataset_path", "skills_path", "patch_pool_path", "log_path", "taxonomy_path"]:
        if key in study_cfg:
            p = Path(study_cfg[key])
            if not p.is_absolute():
                study_cfg[key] = str(project_root / p)

    # Override from CLI args
    if args.dataset:
        study_cfg["dataset_path"] = args.dataset
    if args.selected:
        selected_path = Path(args.selected)
        if not selected_path.is_absolute():
            selected_path = project_root / selected_path
        study_cfg["selected_ids_path"] = str(selected_path)
    if args.concurrency is not None:
        study_cfg["concurrency"] = args.concurrency
    if args.consolidate_limit:
        study_cfg["consolidate_limit"] = args.consolidate_limit

    from src.runner import PRStudyRunner

    runner = PRStudyRunner(config)

    # Determine run mode
    consolidate_only = args.consolidate_only
    validate_only = args.validate

    await runner.run(
        limit=args.limit,
        start_from=args.start_from,
        consolidate_only=consolidate_only,
        validate_only=validate_only,
    )

    # --full: auto-consolidate after processing
    if args.full and not consolidate_only and not validate_only:
        print("\n--- Auto-running Stage 3 consolidation ---")
        await runner.run(consolidate_only=True)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

#!/usr/bin/env python
"""
将聚类结果转为可直接使用的 JSONL 数据集 — 只保留 selected_ids 对应的 PR。

用法:
    python export_clustered.py --dataset path/to/full.jsonl --cluster data/cluster_result.json
    python export_clustered.py --dataset path/to/full.jsonl --cluster data/cluster_result.json --output data/selected.jsonl
"""

import argparse
import json
from pathlib import Path

import yaml


def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def parse_args():
    parser = argparse.ArgumentParser(
        description="将聚类结果导出为 JSONL 子集数据集"
    )
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--dataset", type=str, default=None,
                        help="原始数据集路径 (.jsonl 或 .parquet)")
    parser.add_argument("--cluster", type=str, default="data/cluster_result.json",
                        help="聚类结果文件路径")
    parser.add_argument("--output", type=str, default="data/selected_prs.jsonl",
                        help="输出 JSONL 路径")
    return parser.parse_args()


def main():
    args = parse_args()
    project_root = Path(__file__).parent.resolve()

    config_path = args.config or str(project_root / "config" / "config.yaml")
    config = load_config(config_path)
    study_cfg = config.get("study", {})

    dataset_path = args.dataset or study_cfg.get("dataset_path", "data/input.jsonl")
    if not Path(dataset_path).is_absolute():
        dataset_path = str(project_root / dataset_path)

    cluster_path = args.cluster
    if not Path(cluster_path).is_absolute():
        cluster_path = str(project_root / cluster_path)

    output_path = args.output
    if not Path(output_path).is_absolute():
        output_path = str(project_root / output_path)

    # Load selected IDs
    with open(cluster_path, "r", encoding="utf-8") as f:
        cluster_data = json.load(f)
    selected_set = set(cluster_data["selected_ids"])
    print(f"Selected IDs: {len(selected_set)}")

    # Load and filter dataset
    import pandas as pd

    if dataset_path.endswith(".parquet"):
        df = pd.read_parquet(dataset_path)
    else:
        df = pd.read_json(dataset_path, lines=True)

    filtered = df[df["instance_id"].isin(selected_set)]
    print(f"Matched: {len(filtered)}/{len(df)} PRs")

    # Write JSONL
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    filtered.to_json(output_path, orient="records", lines=True, force_ascii=False)
    print(f"Output: {output_path} ({len(filtered)} records)")


if __name__ == "__main__":
    main()

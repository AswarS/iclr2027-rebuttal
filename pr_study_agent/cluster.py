#!/usr/bin/env python
"""
PR Dataset Clustering — 对数据集聚类后选择代表性 PR 子集。

用法:
    python cluster.py                                    # 默认参数聚类
    python cluster.py --dataset path/to/data.jsonl       # 指定数据集
    python cluster.py --min-cluster-size 10 --reps 3     # 调参
    python cluster.py --no-umap                          # 跳过 UMAP 降维
    python cluster.py --output data/cluster_result.json  # 指定输出路径

输出:
    data/cluster_result.json — 聚类结果 (元数据 + 每簇代表性 PR)
"""

import argparse
import logging
import sys
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
        description="PR Dataset Clustering — 聚类后选择代表性 PR 子集"
    )
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径（默认 config/config.yaml）")
    parser.add_argument("--dataset", type=str, default=None,
                        help="数据集路径 (支持 .jsonl 和 .parquet)")
    parser.add_argument("--output", type=str, default="data/cluster_result.json",
                        help="聚类结果输出路径")
    parser.add_argument("--min-cluster-size", type=int, default=8,
                        help="HDBSCAN min_cluster_size (default: 8)")
    parser.add_argument("--min-samples", type=int, default=5,
                        help="HDBSCAN min_samples (default: 5)")
    parser.add_argument("--reps", type=int, default=2,
                        help="每簇选择的代表性 PR 数 (default: 2)")
    parser.add_argument("--umap-dim", type=int, default=30,
                        help="UMAP 降维目标维度 (default: 30)")
    parser.add_argument("--no-umap", action="store_true",
                        help="跳过 UMAP 降维")
    parser.add_argument("--auto-dim", action="store_true",
                        help="自动搜索最佳 UMAP 维度 (基于 DBCV score)")
    parser.add_argument("--dim-range", type=str, default="15,20,30,40,50",
                        help="自动搜索的维度候选列表 (逗号分隔, default: 15,20,30,40,50)")
    parser.add_argument("--batch-size", type=int, default=256,
                        help="Embedding batch size (default: 256)")
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = parse_args()
    project_root = Path(__file__).parent.resolve()

    config_path = args.config or str(project_root / "config" / "config.yaml")
    config = load_config(config_path)

    study_cfg = config.get("study", {})
    dataset_path = args.dataset or study_cfg.get("dataset_path", "data/input.jsonl")
    if not Path(dataset_path).is_absolute():
        dataset_path = str(project_root / dataset_path)

    output_path = args.output
    if not Path(output_path).is_absolute():
        output_path = str(project_root / output_path)

    from src.pr_parser import load_dataset
    from src.clustering import PRClusterer, build_clustering_texts

    print(f"Loading dataset: {dataset_path}")
    prs = load_dataset(dataset_path)
    print(f"Loaded {len(prs)} PRs")

    instance_ids, texts = build_clustering_texts(prs)

    dim_search_range = [int(x.strip()) for x in args.dim_range.split(",")]

    clusterer = PRClusterer(
        min_cluster_size=args.min_cluster_size,
        min_samples=args.min_samples,
        umap_n_components=args.umap_dim,
        representatives_per_cluster=args.reps,
        use_umap=not args.no_umap,
        auto_search_dim=args.auto_dim,
        dim_search_range=dim_search_range,
    )

    result = clusterer.run(instance_ids, texts, batch_size=args.batch_size)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path)

    m = result.metadata
    print(f"\n{'='*50}")
    print(f"Clustering complete:")
    print(f"  Total PRs:        {m['total_prs']}")
    print(f"  Clusters:         {m['n_clusters']}")
    print(f"  Noise points:     {m['n_noise']}")
    print(f"  Selected PRs:     {m['n_representatives']}")
    print(f"  Compression:      {m['n_representatives']}/{m['total_prs']} "
          f"({m['n_representatives']/m['total_prs']*100:.1f}%)")
    print(f"  Output:           {output_path}")

    # Print cluster size distribution
    sizes = [c["size"] for c in result.clusters]
    if sizes:
        print(f"\n  Cluster size distribution:")
        print(f"    min={min(sizes)}, max={max(sizes)}, "
              f"median={sorted(sizes)[len(sizes)//2]}, mean={sum(sizes)/len(sizes):.1f}")


if __name__ == "__main__":
    main()

"""PR Dataset Clustering — 对 PR 数据集进行语义聚类并选择代表性样本。

流程:
1. 特征提取: problem_statement + change_summary → embedding (all-MiniLM-L12-v2)
2. 降维: UMAP 384d → 30d
3. 聚类: HDBSCAN (密度自适应，无需预设 K)
4. 代表性选择: 每簇选 centroid-nearest + boundary
5. 噪声点全部保留 (独特案例)
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClusterResult:
    """聚类结果。"""
    metadata: Dict[str, Any]
    clusters: List[Dict[str, Any]]
    noise_ids: List[str]
    selected_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata,
            "clusters": self.clusters,
            "noise_ids": self.noise_ids,
            "selected_ids": self.selected_ids,
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def load(path: str) -> "ClusterResult":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ClusterResult(
            metadata=data["metadata"],
            clusters=data["clusters"],
            noise_ids=data["noise_ids"],
            selected_ids=data["selected_ids"],
        )


class PRClusterer:
    """对 PR 数据集做语义聚类并选择代表性样本。"""

    def __init__(
        self,
        min_cluster_size: int = 8,
        min_samples: int = 5,
        umap_n_components: int = 30,
        umap_n_neighbors: int = 15,
        representatives_per_cluster: int = 2,
        use_umap: bool = True,
        auto_search_dim: bool = False,
        dim_search_range: Optional[List[int]] = None,
        random_state: int = 42,
    ):
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.umap_n_components = umap_n_components
        self.umap_n_neighbors = umap_n_neighbors
        self.representatives_per_cluster = representatives_per_cluster
        self.use_umap = use_umap
        self.auto_search_dim = auto_search_dim
        self.dim_search_range = dim_search_range or [15, 20, 30, 40, 50]
        self.random_state = random_state

    def run(
        self,
        instance_ids: List[str],
        texts: List[str],
        embeddings: Optional[np.ndarray] = None,
        batch_size: int = 256,
    ) -> ClusterResult:
        """执行完整聚类流程。

        Args:
            instance_ids: 每条 PR 的 instance_id
            texts: 每条 PR 的文本 (problem_statement + change_summary)
            embeddings: 预计算的 embeddings，如果为 None 则现场计算
            batch_size: embedding 计算的 batch size

        Returns:
            ClusterResult 包含聚类元数据和选中的代表性 PR 列表
        """
        n = len(instance_ids)
        assert len(texts) == n, f"instance_ids ({n}) and texts ({len(texts)}) length mismatch"
        logger.info(f"Starting clustering for {n} PRs")

        # Step 1: Compute embeddings
        if embeddings is None:
            embeddings = self._compute_embeddings(texts, batch_size)
        else:
            assert embeddings.shape[0] == n
        logger.info(f"Embeddings shape: {embeddings.shape}")

        # Step 2: Dimensionality reduction
        if self.use_umap and n > self.umap_n_components + 10:
            if self.auto_search_dim:
                reduced, best_dim = self._auto_search_umap_dim(embeddings)
                self.umap_n_components = best_dim
            else:
                reduced = self._reduce_dimensions(embeddings)
        else:
            reduced = embeddings
            logger.info("Skipping UMAP (data too small or disabled)")

        # Step 3: HDBSCAN clustering
        labels = self._cluster(reduced)
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_noise = int(np.sum(labels == -1))
        logger.info(f"HDBSCAN found {n_clusters} clusters, {n_noise} noise points")

        # Step 4: Select representatives
        clusters_info, selected_ids, noise_ids = self._select_representatives(
            instance_ids, embeddings, labels
        )

        metadata = {
            "total_prs": n,
            "n_clusters": n_clusters,
            "n_noise": n_noise,
            "n_representatives": len(selected_ids),
            "params": {
                "min_cluster_size": self.min_cluster_size,
                "min_samples": self.min_samples,
                "umap_n_components": self.umap_n_components if self.use_umap else None,
                "representatives_per_cluster": self.representatives_per_cluster,
            },
        }

        return ClusterResult(
            metadata=metadata,
            clusters=clusters_info,
            noise_ids=noise_ids,
            selected_ids=selected_ids,
        )

    def _compute_embeddings(self, texts: List[str], batch_size: int) -> np.ndarray:
        """使用 sentence-transformers 批量计算 embeddings。"""
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: all-MiniLM-L12-v2")
        model = SentenceTransformer("all-MiniLM-L12-v2")

        logger.info(f"Computing embeddings for {len(texts)} texts (batch_size={batch_size})")
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        return np.array(embeddings)

    def _reduce_dimensions(self, embeddings: np.ndarray) -> np.ndarray:
        """UMAP 降维。"""
        import umap

        logger.info(
            f"UMAP: {embeddings.shape[1]}d → {self.umap_n_components}d "
            f"(n_neighbors={self.umap_n_neighbors})"
        )
        reducer = umap.UMAP(
            n_components=self.umap_n_components,
            n_neighbors=self.umap_n_neighbors,
            metric="cosine",
            random_state=self.random_state,
            low_memory=True,
        )
        reduced = reducer.fit_transform(embeddings)
        return reduced

    def _auto_search_umap_dim(self, embeddings: np.ndarray) -> Tuple[np.ndarray, int]:
        """自动搜索最佳 UMAP 维度，使用 DBCV (Density-Based Cluster Validity) 评分。"""
        import umap
        import hdbscan

        logger.info(f"Auto-searching UMAP dimensions in {self.dim_search_range}")

        best_score = -np.inf
        best_dim = self.dim_search_range[0]
        best_reduced = None

        for dim in self.dim_search_range:
            logger.info(f"  Trying n_components={dim}...")

            # UMAP 降维
            reducer = umap.UMAP(
                n_components=dim,
                n_neighbors=self.umap_n_neighbors,
                metric="cosine",
                random_state=self.random_state,
                low_memory=True,
            )
            reduced = reducer.fit_transform(embeddings)

            # HDBSCAN 聚类
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=self.min_cluster_size,
                min_samples=self.min_samples,
                cluster_selection_method="eom",
                metric="euclidean",
            )
            clusterer.fit(reduced)

            # 计算 DBCV score (Density-Based Cluster Validity)
            # 范围 [-1, 1]，越高越好，表示簇内紧密、簇间分离
            score = clusterer.relative_validity_
            n_clusters = len(set(clusterer.labels_)) - (1 if -1 in clusterer.labels_ else 0)
            n_noise = int(np.sum(clusterer.labels_ == -1))

            logger.info(f"    DBCV={score:.4f}, clusters={n_clusters}, noise={n_noise}")

            if score > best_score:
                best_score = score
                best_dim = dim
                best_reduced = reduced

        logger.info(f"Best dimension: {best_dim} (DBCV={best_score:.4f})")
        return best_reduced, best_dim

    def _cluster(self, data: np.ndarray) -> np.ndarray:
        """HDBSCAN 聚类。"""
        import hdbscan

        logger.info(
            f"HDBSCAN: min_cluster_size={self.min_cluster_size}, "
            f"min_samples={self.min_samples}"
        )
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            cluster_selection_method="eom",
            metric="euclidean",
        )
        clusterer.fit(data)
        return clusterer.labels_

    def _select_representatives(
        self,
        instance_ids: List[str],
        embeddings: np.ndarray,
        labels: np.ndarray,
    ) -> Tuple[List[Dict], List[str], List[str]]:
        """每簇选代表性 PR：centroid-nearest (典型) + farthest (边界)。
        噪声点全部保留。
        """
        clusters_info = []
        selected_ids = []
        noise_ids = []

        unique_labels = sorted(set(labels))

        for label in unique_labels:
            mask = labels == label
            indices = np.where(mask)[0]
            ids_in_cluster = [instance_ids[i] for i in indices]

            if label == -1:
                noise_ids = ids_in_cluster
                selected_ids.extend(ids_in_cluster)
                continue

            cluster_embeddings = embeddings[indices]
            centroid = cluster_embeddings.mean(axis=0)

            # Cosine distance to centroid
            norms = np.linalg.norm(cluster_embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            normalized = cluster_embeddings / norms
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm > 0:
                centroid_normalized = centroid / centroid_norm
            else:
                centroid_normalized = centroid
            similarities = normalized @ centroid_normalized
            distances = 1 - similarities

            # Select representatives
            reps = []
            n_reps = min(self.representatives_per_cluster, len(indices))

            # 1. Most typical (closest to centroid)
            typical_idx = int(np.argmin(distances))
            reps.append(instance_ids[indices[typical_idx]])

            # 2. Boundary (farthest from centroid) — if we want 2 reps
            if n_reps >= 2 and len(indices) > 1:
                boundary_idx = int(np.argmax(distances))
                if boundary_idx != typical_idx:
                    reps.append(instance_ids[indices[boundary_idx]])

            selected_ids.extend(reps)

            clusters_info.append({
                "cluster_id": int(label),
                "size": len(indices),
                "representative_ids": reps,
                "all_ids": ids_in_cluster,
            })

        return clusters_info, selected_ids, noise_ids


def build_clustering_texts(prs) -> Tuple[List[str], List[str]]:
    """从 PRData 列表构建聚类输入。

    Returns:
        (instance_ids, texts) 元组
    """
    instance_ids = []
    texts = []
    for pr in prs:
        instance_ids.append(pr.instance_id)
        text = f"{pr.problem_statement}\n\n{pr.change_summary}"
        texts.append(text)
    return instance_ids, texts

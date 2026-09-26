"""PR-RAG retrieval: retrieve similar PRs from a JSONL dataset as skill content.

Ablation experiment 1: Instead of using structured skills (3-layer hierarchy),
retrieve the most similar PR from the training/test set and return its
problem_statement + patch + hints_text as guidance.

Uses embedding-based cosine similarity for retrieval.
Excludes the current instance to avoid data leakage.

Embedding strategy:
  - Pool embeddings: PRE-COMPUTED offline via `python -m minisweagent.skills.retrieval_pr_rag`
    and saved as .npy file next to the JSONL. This avoids computing 19k embeddings at runtime.
  - Query embedding: Computed at runtime using the same local model (sentence-transformers).
  - Falls back to OpenAI API only if MSWEA_EMBEDDING_BACKEND=openai is set explicitly.

Run the precompute script once:
    python -m minisweagent.skills.retrieval_pr_rag --data path/to/swe-bench.jsonl
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger("minisweagent.skills.retrieval_pr_rag")

# ── Configuration ────────────────────────────────────────────────────────────

DEFAULT_PR_POOL_PATH = r"D:\Document\Study\experiment\code\SWE\swe_data\swe-bench-lite_test.jsonl"
DEFAULT_TOP_K = 1
DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"  # 384-dim, fast, ~80MB

# ── Caches ───────────────────────────────────────────────────────────────────

_pr_pool_cache: Optional[List[dict]] = None
_embedding_matrix: Optional[np.ndarray] = None
_local_model = None  # Lazy-loaded SentenceTransformer


def _load_pr_pool(pool_path: str) -> List[dict]:
    """Load all PR records from the JSONL file."""
    global _pr_pool_cache
    if _pr_pool_cache is not None:
        return _pr_pool_cache

    records = []
    with open(pool_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    _pr_pool_cache = records
    logger.info(f"Loaded {len(records)} PRs from {pool_path}")
    return records


# ── Embedding: local sentence-transformers (default) ─────────────────────────


def _get_local_model():
    """Lazy-load sentence-transformers model."""
    global _local_model
    if _local_model is not None:
        return _local_model

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError(
            "sentence-transformers not installed. Run: pip install sentence-transformers\n"
            "Or set MSWEA_EMBEDDING_BACKEND=openai to use OpenAI API instead."
        )

    model_name = os.environ.get("MSWEA_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_MODEL)
    logger.info(f"Loading local embedding model: {model_name}")
    _local_model = SentenceTransformer(model_name)
    return _local_model


def _embed_local(texts: List[str], show_progress: bool = False) -> np.ndarray:
    """Embed texts using local sentence-transformers model."""
    model = _get_local_model()
    embeddings = model.encode(
        texts,
        show_progress_bar=show_progress,
        batch_size=64,
        normalize_embeddings=True,
    )
    return np.array(embeddings, dtype=np.float32)


def _embed_query_local(text: str) -> np.ndarray:
    """Embed a single query text."""
    model = _get_local_model()
    embedding = model.encode([text[:10000], ], normalize_embeddings=True)
    return np.array(embedding[0], dtype=np.float32)


# ── Embedding: OpenAI API (fallback) ────────────────────────────────────────


def _embed_openai_batch(texts: List[str], client, model_name: str) -> np.ndarray:
    """Embed texts using OpenAI embedding API."""
    texts = [t[:30000] for t in texts]
    all_embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(model=model_name, input=batch)
        batch_embeddings = [np.array(d.embedding, dtype=np.float32) for d in response.data]
        all_embeddings.extend(batch_embeddings)
        if (i // batch_size) % 10 == 0:
            logger.info(f"  Embedded {i + len(batch)}/{len(texts)} ...")
    return np.array(all_embeddings)


def _embed_openai_single(text: str, client, model_name: str) -> np.ndarray:
    """Embed a single text using OpenAI API."""
    text = text[:30000]
    response = client.embeddings.create(model=model_name, input=text)
    return np.array(response.data[0].embedding, dtype=np.float32)


# ── Index management ─────────────────────────────────────────────────────────


def _get_cache_path(pool_path: str) -> Path:
    """Get the .npy cache path for a given JSONL pool file."""
    backend = os.environ.get("MSWEA_EMBEDDING_BACKEND", "local")
    if backend == "local":
        model_name = os.environ.get("MSWEA_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_MODEL)
        suffix = f".embeddings.{model_name.replace('/', '_')}.npy"
    else:
        emb_model = os.environ.get("MSWEA_EMBEDDING_MODEL", "text-embedding-3-small")
        suffix = f".embeddings.{emb_model.replace('/', '_')}.npy"
    return Path(pool_path).with_suffix(suffix)


def _load_embedding_index(records: List[dict], client=None) -> Optional[np.ndarray]:
    """Load pre-computed embedding matrix from cache file.

    Returns None if cache doesn't exist (you need to run precompute first).
    """
    global _embedding_matrix
    if _embedding_matrix is not None:
        return _embedding_matrix

    pool_path = os.environ.get("MSWEA_PR_POOL_PATH", DEFAULT_PR_POOL_PATH)
    cache_path = _get_cache_path(pool_path)

    if cache_path.exists():
        logger.info(f"Loading cached embeddings from {cache_path}")
        _embedding_matrix = np.load(str(cache_path))
        if _embedding_matrix.shape[0] == len(records):
            logger.info(f"Embedding matrix loaded: shape={_embedding_matrix.shape}")
            return _embedding_matrix
        else:
            logger.warning(
                f"Cache size mismatch: cache={_embedding_matrix.shape[0]}, records={len(records)}. "
                f"Please re-run precompute."
            )
            _embedding_matrix = None

    # If no cache, try to compute on-the-fly (only reasonable for small datasets)
    if len(records) <= 500:
        logger.info(f"No cache found, computing embeddings for {len(records)} PRs on-the-fly...")
        backend = os.environ.get("MSWEA_EMBEDDING_BACKEND", "local")
        texts = [r.get("problem_statement", "") for r in records]

        if backend == "openai" and client is not None:
            emb_model = os.environ.get("MSWEA_EMBEDDING_MODEL", "text-embedding-3-small")
            _embedding_matrix = _embed_openai_batch(texts, client, emb_model)
        else:
            _embedding_matrix = _embed_local(texts, show_progress=True)

        # Save cache for next time
        try:
            np.save(str(cache_path), _embedding_matrix)
            logger.info(f"Saved embedding cache to {cache_path}")
        except OSError as e:
            logger.warning(f"Failed to save cache: {e}")

        return _embedding_matrix

    # Large dataset without cache — refuse to compute at runtime
    logger.error(
        f"No pre-computed embeddings found at {cache_path}. "
        f"Dataset has {len(records)} records — too large for runtime computation. "
        f"Run precompute first:\n"
        f"  python -m minisweagent.skills.retrieval_pr_rag --data {pool_path}"
    )
    return None


def _cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between query vector and all rows in matrix."""
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    matrix_norms = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
    return matrix_norms @ query_norm


def _format_pr_as_skill(record: dict, rank: int = 1) -> str:
    """Format a PR record as skill content for the agent."""
    parts = []
    parts.append(f"## Reference PR #{rank}")
    parts.append("")

    # Problem statement
    problem = record.get("problem_statement", "").strip()
    if problem:
        parts.append("### Problem Description")
        parts.append(problem)
        parts.append("")

    # Hints
    hints = record.get("hints_text", "").strip()
    if hints:
        parts.append("### Hints")
        parts.append(hints)
        parts.append("")

    # Patch (the gold solution)
    patch = record.get("patch", "").strip()
    if patch:
        parts.append("### Solution Patch")
        parts.append("```diff")
        parts.append(patch)
        parts.append("```")
        parts.append("")

    return "\n".join(parts)


# ── Public API ───────────────────────────────────────────────────────────────


def retrieve_pr_content(
    task: str,
    client=None,
    model_name: str = "",
    *,
    instance_id: str = "",
    top_k: Optional[int] = None,
) -> str:
    """Retrieve the most similar PR(s) from the pool and format as skill content.

    Args:
        task: The current bug/task description (problem_statement).
        client: OpenAI-compatible client (only needed if MSWEA_EMBEDDING_BACKEND=openai).
        model_name: Not used for local embedding, kept for interface compatibility.
        instance_id: Current instance ID to exclude from results (avoid leakage).
        top_k: Number of similar PRs to return. Defaults to MSWEA_PR_RAG_TOP_K or 1.

    Returns:
        Formatted string containing the most similar PR(s) as reference.
    """
    pool_path = os.environ.get("MSWEA_PR_POOL_PATH", DEFAULT_PR_POOL_PATH)

    if top_k is None:
        top_k = int(os.environ.get("MSWEA_PR_RAG_TOP_K", str(DEFAULT_TOP_K)))

    # Load PR pool
    try:
        records = _load_pr_pool(pool_path)
    except Exception as e:
        logger.error(f"Failed to load PR pool from {pool_path}: {e}")
        return ""

    if not records:
        return ""

    # Load embedding index (pre-computed)
    embedding_matrix = _load_embedding_index(records, client)
    if embedding_matrix is None:
        return ""

    # Get query embedding
    backend = os.environ.get("MSWEA_EMBEDDING_BACKEND", "local")
    try:
        if backend == "openai" and client is not None:
            emb_model = os.environ.get("MSWEA_EMBEDDING_MODEL", "text-embedding-3-small")
            query_embedding = _embed_openai_single(task, client, emb_model)
        else:
            query_embedding = _embed_query_local(task)
    except Exception as e:
        logger.error(f"Failed to compute query embedding: {e}")
        return ""

    # Dimension check
    if query_embedding.shape[0] != embedding_matrix.shape[1]:
        logger.error(
            f"Embedding dimension mismatch: query={query_embedding.shape[0]}, "
            f"index={embedding_matrix.shape[1]}. Ensure same model for precompute and query."
        )
        return ""

    # Compute similarities
    similarities = _cosine_similarity(query_embedding, embedding_matrix)

    # Exclude current instance
    if instance_id:
        for i, record in enumerate(records):
            if record.get("instance_id") == instance_id:
                similarities[i] = -1.0

    # Get top-k indices
    top_indices = np.argsort(similarities)[::-1][:top_k]

    # Format results
    parts = []
    parts.append("# Reference: Similar PR Solutions")
    parts.append("")
    parts.append(
        "Below are similar PRs from the codebase history. "
        "Use them as reference for understanding the fix pattern, "
        "but adapt the solution to the current problem."
    )
    parts.append("")

    for rank, idx in enumerate(top_indices, 1):
        record = records[idx]
        sim_score = similarities[idx]
        logger.info(
            f"PR-RAG top-{rank}: {record.get('instance_id', '?')} "
            f"(similarity={sim_score:.4f})"
        )
        parts.append(_format_pr_as_skill(record, rank))

    return "\n".join(parts)


def reset_cache():
    """Reset the in-memory caches."""
    global _pr_pool_cache, _embedding_matrix, _local_model
    _pr_pool_cache = None
    _embedding_matrix = None
    _local_model = None


# ── Precompute CLI ───────────────────────────────────────────────────────────


def precompute_embeddings(data_path: str):
    """Pre-compute and save embedding matrix for a JSONL dataset."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    pool_path = data_path
    cache_path = _get_cache_path(pool_path)

    print(f"Loading data from: {pool_path}")
    records = _load_pr_pool(pool_path)
    print(f"Total records: {len(records)}")
    print(f"Cache will be saved to: {cache_path}")

    if cache_path.exists():
        existing = np.load(str(cache_path))
        if existing.shape[0] == len(records):
            print(f"Cache already exists with correct size {existing.shape}. Skipping.")
            return
        print(f"Cache exists but size mismatch ({existing.shape[0]} vs {len(records)}). Recomputing.")

    texts = [r.get("problem_statement", "") for r in records]

    backend = os.environ.get("MSWEA_EMBEDDING_BACKEND", "local")
    if backend == "openai":
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )
        emb_model = os.environ.get("MSWEA_EMBEDDING_MODEL", "text-embedding-3-small")
        print(f"Using OpenAI embedding: {emb_model}")
        matrix = _embed_openai_batch(texts, client, emb_model)
    else:
        model_name = os.environ.get("MSWEA_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_MODEL)
        print(f"Using local embedding model: {model_name}")
        matrix = _embed_local(texts, show_progress=True)

    np.save(str(cache_path), matrix)
    print(f"Saved embeddings: shape={matrix.shape}, path={cache_path}")
    print("Done! You can now run experiments with MSWEA_RETRIEVAL_MODE=pr_rag")


if __name__ == "__main__":
    # CLI: python -m minisweagent.skills.retrieval_pr_rag --data path/to/file.jsonl
    # Or:  python retrieval_pr_rag.py --data path/to/file.jsonl
    import argparse
    parser = argparse.ArgumentParser(description="Precompute PR embeddings for PR-RAG retrieval")
    parser.add_argument("--data", "-d", required=True, help="Path to JSONL file")
    args = parser.parse_args()
    precompute_embeddings(args.data)

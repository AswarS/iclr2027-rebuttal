"""Flat Memory retrieval: retrieve atomic skills from patch_pool without aggregation.

Ablation experiment 2: Instead of using the 3-layer hierarchical structure
(general → domain → scenario), directly retrieve the most similar atomic skill
from skills/patch_pool/ using embedding cosine similarity.

This tests whether the hierarchical aggregation adds value over flat retrieval.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger("retrieval_flat")

# ── Configuration ────────────────────────────────────────────────────────────

from minisweagent.skills import _get_skills_dir
SKILLS_DIR = _get_skills_dir()
DEFAULT_TOP_K = 1


# ── Cache ────────────────────────────────────────────────────────────────────

_flat_skills_cache: Optional[List[dict]] = None
_flat_embeddings: Optional[np.ndarray] = None


def _load_flat_skills(skills_dir: Path) -> List[dict]:
    """Load all atomic skills from patch_pool directory."""
    global _flat_skills_cache
    if _flat_skills_cache is not None:
        return _flat_skills_cache

    patch_pool_dir = skills_dir / "patch_pool"
    if not patch_pool_dir.exists():
        logger.warning(f"patch_pool directory not found: {patch_pool_dir}")
        return []

    skills = []
    for f in sorted(patch_pool_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_file"] = f.name
            skills.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load {f}: {e}")

    _flat_skills_cache = skills
    logger.info(f"Loaded {len(skills)} atomic skills from patch_pool")
    return skills


def _get_flat_embeddings(skills: List[dict]) -> Optional[np.ndarray]:
    """Extract pre-computed embeddings from atomic skills."""
    global _flat_embeddings
    if _flat_embeddings is not None:
        return _flat_embeddings

    embeddings = []
    for skill in skills:
        emb = skill.get("embedding")
        if emb and len(emb) > 0:
            embeddings.append(np.array(emb, dtype=np.float32))
        else:
            logger.warning(f"Skill {skill.get('_file', '?')} has no embedding, skipping")
            return None

    if not embeddings:
        return None

    _flat_embeddings = np.array(embeddings)
    return _flat_embeddings


def _get_query_embedding(text: str, client, model_name: str = "text-embedding-3-small") -> np.ndarray:
    """Get embedding for the query text using OpenAI API."""
    text = text[:30000]
    response = client.embeddings.create(
        model=model_name,
        input=text,
    )
    return np.array(response.data[0].embedding, dtype=np.float32)


def _cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between query and all rows in matrix."""
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    matrix_norms = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
    return matrix_norms @ query_norm


def _format_flat_skill(skill: dict, rank: int = 1) -> str:
    """Format a flat atomic skill as content for the agent."""
    parts = []
    parts.append(f"## Relevant Pattern #{rank}: {skill.get('dimension_label', 'unknown')}")
    parts.append("")

    # Tags info
    tags = skill.get("tags", {})
    if tags:
        domain = tags.get("domain", [])
        pattern = tags.get("problem_pattern", [])
        if domain:
            parts.append(f"**Domain**: {', '.join(domain)}")
        if pattern:
            parts.append(f"**Pattern**: {', '.join(pattern)}")
        parts.append("")

    # Main content
    content = skill.get("content", "").strip()
    if content:
        parts.append(content)
        parts.append("")

    return "\n".join(parts)


# ── Public API ───────────────────────────────────────────────────────────────


def retrieve_flat_skill(
    task: str,
    client,
    model_name: str,
    *,
    top_k: Optional[int] = None,
) -> str:
    """Retrieve the most similar atomic skill(s) from patch_pool using embedding similarity.

    No hierarchical aggregation — just flat cosine similarity retrieval.

    Args:
        task: The current bug/task description.
        client: OpenAI-compatible client (for computing query embedding).
        model_name: Not used for embedding, kept for interface compatibility.
        top_k: Number of skills to return. Defaults to MSWEA_FLAT_TOP_K or 1.

    Returns:
        Formatted string with the most similar atomic skill content.
    """
    skills_dir_env = os.environ.get("MSWEA_SKILLS_DIR")
    skills_dir = Path(skills_dir_env) if skills_dir_env else SKILLS_DIR

    if top_k is None:
        top_k = int(os.environ.get("MSWEA_FLAT_TOP_K", str(DEFAULT_TOP_K)))

    # Load atomic skills
    skills = _load_flat_skills(skills_dir)
    if not skills:
        logger.warning("No atomic skills available for flat retrieval")
        return ""

    # Get pre-computed embeddings
    embeddings = _get_flat_embeddings(skills)
    if embeddings is None:
        logger.warning("No embeddings available in atomic skills, falling back to first skill")
        return _format_flat_skill(skills[0], 1)

    # Compute query embedding
    embedding_model = os.environ.get("MSWEA_EMBEDDING_MODEL", "text-embedding-3-small")
    try:
        query_embedding = _get_query_embedding(task, client, embedding_model)
    except Exception as e:
        logger.error(f"Failed to compute query embedding: {e}")
        return _format_flat_skill(skills[0], 1)

    # Check dimension compatibility
    if query_embedding.shape[0] != embeddings.shape[1]:
        logger.warning(
            f"Embedding dimension mismatch: query={query_embedding.shape[0]}, "
            f"pool={embeddings.shape[1]}. Falling back to first skill."
        )
        return _format_flat_skill(skills[0], 1)

    # Compute similarities and rank
    similarities = _cosine_similarity(query_embedding, embeddings)
    top_indices = np.argsort(similarities)[::-1][:top_k]

    # Format results
    parts = []
    parts.append("# Skill Reference (Flat Retrieval)")
    parts.append("")
    parts.append(
        "Below is the most relevant pattern from the skill pool. "
        "Apply this pattern to guide your fix."
    )
    parts.append("")

    for rank, idx in enumerate(top_indices, 1):
        skill = skills[idx]
        sim_score = similarities[idx]
        logger.info(
            f"Flat top-{rank}: {skill.get('dimension_label', '?')} "
            f"(similarity={sim_score:.4f})"
        )
        parts.append(_format_flat_skill(skill, rank))

    return "\n".join(parts)


def reset_cache():
    """Reset in-memory caches."""
    global _flat_skills_cache, _flat_embeddings
    _flat_skills_cache = None
    _flat_embeddings = None

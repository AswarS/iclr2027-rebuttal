"""Local embedding client using sentence-transformers."""

import logging
from typing import List
import numpy as np

logger = logging.getLogger(__name__)

_model_cache = {}


class LocalEmbedder:
    """Local embedding using sentence-transformers (all-MiniLM-L12-v2)."""

    def __init__(self, model_name: str = "all-MiniLM-L12-v2"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            if self.model_name in _model_cache:
                self._model = _model_cache[self.model_name]
            else:
                from sentence_transformers import SentenceTransformer
                import time
                logger.info(f"Loading embedding model: {self.model_name}")

                # Retry logic for network issues
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        self._model = SentenceTransformer(
                            self.model_name,
                            cache_folder=None,  # Use default cache
                            device='cpu'  # Force CPU to avoid CUDA issues
                        )
                        _model_cache[self.model_name] = self._model
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                            logger.warning(f"Failed to load model (attempt {attempt+1}/{max_retries}): {e}")
                            logger.info(f"Retrying in {wait_time}s...")
                            time.sleep(wait_time)
                        else:
                            logger.error(f"Failed to load model after {max_retries} attempts")
                            raise
        return self._model

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Compute embeddings for a list of texts. Returns list of float vectors."""
        if not texts:
            return []
        model = self._get_model()
        embeddings = model.encode(texts, normalize_embeddings=True)
        return [emb.tolist() for emb in embeddings]

    def embed_single(self, text: str) -> List[float]:
        """Compute embedding for a single text."""
        if not text:
            return []
        result = self.embed([text])
        return result[0] if result else []


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    va, vb = np.array(a), np.array(b)
    norm_a, norm_b = np.linalg.norm(va), np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))

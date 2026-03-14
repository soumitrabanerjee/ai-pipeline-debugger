"""
embedder.py — Generates 384-dim text embeddings using sentence-transformers.

Model: all-MiniLM-L6-v2 (runs locally inside the container — no API key required).
Dimension: 384 (matches EMBED_DIM in shared/models.py).

The model is downloaded once on first use and cached in ~/.cache/torch/sentence_transformers.
Subsequent calls are fast (CPU inference ~10ms per short string).
"""

import os
from functools import lru_cache

EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
EMBED_DIM   = 384


@lru_cache(maxsize=1)
def _get_model():
    """Load model once, cache for lifetime of process."""
    try:
        from sentence_transformers import SentenceTransformer
        print(f"[embedder] Loading model '{EMBED_MODEL}'...")
        model = SentenceTransformer(EMBED_MODEL)
        print(f"[embedder] Model loaded — dim={EMBED_DIM}")
        return model
    except Exception as e:
        print(f"[embedder] Failed to load model: {e}")
        return None


def embed(text: str) -> list[float] | None:
    """
    Return a 384-dim embedding vector for the given text, or None on failure.
    Failure is non-fatal — the pipeline continues without RAG context.
    """
    model = _get_model()
    if model is None:
        return None
    try:
        # encode() returns a numpy array; tolist() converts to plain Python list
        vec = model.encode(text[:2000], normalize_embeddings=True)
        return vec.tolist()
    except Exception as e:
        print(f"[embedder] Embedding failed: {e}")
        return None

"""Text embedding using sentence-transformers."""

from typing import Any

import structlog

from doc_agent.config import get_settings

logger = structlog.get_logger()

_model = None


def get_embedder() -> Any:
    """Get or create the embedding model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        settings = get_settings()
        _model = SentenceTransformer(settings.embeddings_model)
        logger.info("Embedding model loaded", model=settings.embeddings_model)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts."""
    model = get_embedder()
    settings = get_settings()
    embeddings = model.encode(
        texts,
        batch_size=settings.embeddings_batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return embeddings.tolist()


def embed_query(text: str) -> list[float]:
    """Embed a single query text."""
    return embed_texts([text])[0]

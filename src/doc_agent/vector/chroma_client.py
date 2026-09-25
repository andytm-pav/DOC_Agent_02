"""ChromaDB client wrapper with retry logic."""

from pathlib import Path
from typing import Any

import chromadb
import structlog

from doc_agent.config import get_settings

logger = structlog.get_logger()

_client: chromadb.ClientAPI | None = None


def get_client() -> chromadb.ClientAPI:
    """Get or create ChromaDB client."""
    global _client
    if _client is None:
        settings = get_settings()
        chroma_dir = Path(settings.data_dir) / "chroma"
        chroma_dir.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(chroma_dir))
    return _client


def get_or_create_collection(name: str = "chunks") -> chromadb.Collection:
    """Get or create a ChromaDB collection."""
    client = get_client()
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    """Add chunks to ChromaDB with retry."""
    collection = get_or_create_collection()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            return
        except Exception as e:
            logger.warning("ChromaDB add failed", attempt=attempt + 1, error=str(e))
            if attempt == max_retries - 1:
                raise
            import time
            time.sleep(0.5 * (attempt + 1))


def query_chunks(
    query_embedding: list[float],
    n_results: int = 20,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Query chunks by embedding."""
    collection = get_or_create_collection()
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
    )


def delete_by_file_id(file_id: int) -> None:
    """Delete all chunks for a file."""
    collection = get_or_create_collection()
    # Get all chunk IDs for this file
    results = collection.get(where={"file_id": file_id})
    if results["ids"]:
        collection.delete(ids=results["ids"])


def check_chroma() -> bool:
    """Check if ChromaDB is accessible."""
    try:
        client = get_client()
        client.list_collections()
        return True
    except Exception:
        return False

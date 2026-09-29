"""ChromaDB-обёртка с retry + автоматический fallback на LiteVectorStore (E005).

Метаданные чанка: {file_id, chunk_index, page, doc_type, contract_no, city}.
Размерность 384, метрика cosine (ТЗ 5.2).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from doc_agent.config import load_settings
from doc_agent.logging import get_logger
from doc_agent.vector.embedder import DIM

log = get_logger("vector.store")


class VectorStore(Protocol):
    def upsert_chunks(self, ids: list[str], embeddings: list[list[float]],
                      documents: list[str], metadatas: list[dict]) -> None: ...
    def query(self, embedding: list[float], n: int = 20,
              file_ids: list[int] | None = None) -> list[dict]: ...
    def delete_file(self, file_id: int) -> None: ...
    def healthy(self) -> bool: ...
    def count(self) -> int: ...


class ChromaVectorStore:
    def __init__(self, path: Path, collection: str) -> None:
        import chromadb  # локальный импорт: fallback при недоступности
        from chromadb.config import Settings as ChromaSettings

        # Телеметрия отключена: ТЗ запрещает обращения в интернет
        self.client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(self, ids: list[str], embeddings: list[list[float]],
                      documents: list[str], metadatas: list[dict]) -> None:
        for attempt in range(3):
            try:
                self.collection.upsert(ids=ids, embeddings=embeddings,  # type: ignore[arg-type]
                                       documents=documents, metadatas=metadatas)  # type: ignore[arg-type]
                return
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    raise
                log.warning("chroma_retry", attempt=attempt + 1, error=str(exc))
                time.sleep(0.5 * (attempt + 1))

    def query(self, embedding: list[float], n: int = 20,
              file_ids: list[int] | None = None) -> list[dict]:
        where: Any = {"file_id": {"$in": file_ids}} if file_ids else {}
        res = self.collection.query(query_embeddings=[embedding], n_results=n, where=where or None)  # type: ignore[arg-type,dict-item]
        out: list[dict] = []
        if not res.get("ids") or not res["ids"][0]:
            return out
        for i, cid in enumerate(res["ids"][0]):
            dist = (res.get("distances") or [[0.0]])[0][i]
            meta = (res.get("metadatas") or [[{}]])[0][i] or {}
            doc = (res.get("documents") or [[""]])[0][i] or ""
            out.append({
                "chunk_key": cid,
                "file_id": int(meta.get("file_id", 0)),
                "chunk_index": int(meta.get("chunk_index", 0)),
                "page": meta.get("page"),
                "text": doc,
                "score": 1.0 - float(dist),  # cosine distance -> similarity
            })
        return out

    def delete_file(self, file_id: int) -> None:
        self.collection.delete(where={"file_id": {"$eq": file_id}})  # type: ignore[arg-type,dict-item]

    def healthy(self) -> bool:
        try:
            self.collection.count()
            return True
        except Exception:  # noqa: BLE001
            return False

    def count(self) -> int:
        return int(self.collection.count())


class LiteVectorStore:
    """Встроенный векторный store (JSON на диске, косинус на чистом Python).

    Используется, если ChromaDB недоступна (E005) или vector.backend: lite.
    """

    def __init__(self, path: Path, collection: str) -> None:
        self.file = path / f"{collection}.lite.json"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        if self.file.exists():
            self._data = json.loads(self.file.read_text(encoding="utf-8"))

    def _flush(self) -> None:
        self.file.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def upsert_chunks(self, ids: list[str], embeddings: list[list[float]],
                      documents: list[str], metadatas: list[dict]) -> None:
        with self._lock:
            for cid, emb, doc, meta in zip(ids, embeddings, documents, metadatas):
                self._data[cid] = {"embedding": emb, "text": doc, "meta": meta}
            self._flush()

    def query(self, embedding: list[float], n: int = 20,
              file_ids: list[int] | None = None) -> list[dict]:
        q = embedding
        qnorm = sum(v * v for v in q) ** 0.5 or 1.0
        scored: list[dict] = []
        with self._lock:
            for cid, item in self._data.items():
                meta = item["meta"]
                if file_ids and int(meta.get("file_id", 0)) not in file_ids:
                    continue
                vec = item["embedding"]
                dot = sum(a * b for a, b in zip(q, vec))
                vnorm = sum(v * v for v in vec) ** 0.5 or 1.0
                scored.append({
                    "chunk_key": cid,
                    "file_id": int(meta.get("file_id", 0)),
                    "chunk_index": int(meta.get("chunk_index", 0)),
                    "page": meta.get("page"),
                    "text": item["text"],
                    "score": dot / (qnorm * vnorm),
                })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:n]

    def delete_file(self, file_id: int) -> None:
        with self._lock:
            for cid in [k for k, v in self._data.items() if int(v["meta"].get("file_id", 0)) == file_id]:
                del self._data[cid]
            self._flush()

    def healthy(self) -> bool:
        return self.file.parent.exists()

    def count(self) -> int:
        return len(self._data)


_store: VectorStore | None = None
_degraded = False
_lock = threading.Lock()


def get_vector_store() -> VectorStore:
    """Фабрика: chroma -> lite fallback (E005: health=degraded, поиск по BM25 живёт).

    v2.7: при vector.auto_collection_suffix имя коллекции получает суффикс
    векторного пространства (embedding_space_id: backend-модель-hash).
    Смена backend/модели эмбеддингов больше НЕ смешивает старые и новые
    векторы в одной коллекции — новая переиндексация пишется в новую
    коллекцию, старая остаётся нетронутой (можно вернуться сменой конфига).
    """
    global _store, _degraded
    with _lock:
        if _store is not None:
            return _store
        s = load_settings()
        path = s.app.sub_dir("chroma")
        collection = s.vector.collection
        if s.vector.auto_collection_suffix:
            from doc_agent.vector.embedder import embedding_space_id

            collection = f"{collection}-{embedding_space_id()}"
        if s.vector.backend == "chroma":
            try:
                _store = ChromaVectorStore(path, collection)
                _store.count()  # прогрев
                return _store
            except Exception as exc:  # noqa: BLE001
                log.warning("chroma_unavailable_fallback_lite", error=str(exc))
        _store = LiteVectorStore(path, collection)
        _degraded = s.vector.backend == "chroma"
        return _store


def reset_vector_store() -> None:
    global _store, _degraded
    with _lock:
        _store = None
        _degraded = False


def vector_degraded() -> bool:
    return _degraded


def make_chunk_key(file_id: int, chunk_index: int) -> str:
    return f"{file_id}:{chunk_index}"


def vector_info() -> dict:
    store = get_vector_store()
    from doc_agent.vector.embedder import resolve_backend

    collection = getattr(store, "collection", None)
    name = getattr(collection, "name", None)
    if name is None and hasattr(store, "file"):
        name = store.file.stem
    return {
        "backend": type(store).__name__,
        "count": store.count(),
        "dim": DIM,
        "embeddings": resolve_backend(),
        "collection": name,
    }

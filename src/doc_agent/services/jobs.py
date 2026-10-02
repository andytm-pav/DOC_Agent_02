"""Воркер очереди jobs: poll-цикл, приоритеты, retry, обработчики.

kinds: ingest | reindex:<file_id> | reprocess:<file_id> | reindex_all |
       reproduce:<format>:<file_id>

reindex:<id>   — быстрая переэмбеддировка УЖЕ готовых чанков (после
                 OCR-исправления текста чанков в БД);
reprocess:<id> — ПОЛНАЯ переобработка из оригинала (извлечение, чанки с
                 текущими настройками, эмбеддинги) — v2.6.1;
reindex_all    — полная переобработка ВСЕХ файлов (кнопка «Полная
                 переиндексация» в админ-панели) — v2.6.1: раньше только
                 переэмбеддировка, из-за чего новые настройки чанкинга
                 (filename_prefix) не применялись к старым файлам.
"""
from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import select

from doc_agent.db.migrations import log_audit
from doc_agent.db.models import Chunk, File, Job
from doc_agent.db.session import get_session_factory
from doc_agent.logging import get_logger
from doc_agent.services import ingest
from doc_agent.vector.chroma_client import get_vector_store, make_chunk_key
from doc_agent.vector.embedder import embed_passages

log = get_logger("services.jobs")

_stop = threading.Event()
_thread: threading.Thread | None = None


def _handle(job: Job) -> None:
    if job.kind == "ingest" and job.file_id:
        ingest.process_file(job.file_id)
    elif job.kind.startswith("reindex:"):
        file_id = int(job.kind.split(":", 1)[1])
        _reindex_file(file_id)
    elif job.kind.startswith("reprocess:"):
        file_id = int(job.kind.split(":", 1)[1])
        ingest.process_file(file_id)
    elif job.kind == "reindex_all":
        factory = get_session_factory()
        with factory() as db:
            ids = db.execute(select(File.id)).scalars().all()
        for fid in ids:
            ingest.process_file(fid)
    elif job.kind.startswith("reproduce:") and job.file_id:
        target_format = job.kind.split(":", 1)[1]
        from doc_agent.services import reproduce as reproduce_service

        reproduce_service.finish_reproduce(job.file_id, job.id, target_format)
    else:
        raise ValueError(f"Неизвестный тип задачи: {job.kind}")


def _reindex_file(file_id: int) -> None:
    """Переиндексация чанков файла (после OCR-исправления / полная)."""
    factory = get_session_factory()
    with factory() as db:
        f = db.get(File, file_id)
        if f is None:
            return
        chunks = db.execute(select(Chunk).where(Chunk.file_id == file_id)).scalars().all()
        store = get_vector_store()
        store.delete_file(file_id)
        if chunks:
            embeddings = embed_passages([c.text for c in chunks])
            store.upsert_chunks(
                ids=[make_chunk_key(file_id, c.chunk_index) for c in chunks],
                embeddings=embeddings,
                documents=[c.text for c in chunks],
                metadatas=[{
                    "file_id": file_id, "chunk_index": c.chunk_index, "page": c.page or 1,
                    "doc_type": f.doc_type or "other",
                    "contract_no": f.contract_no or "", "city": f.city or "",
                } for c in chunks],
            )
    log.info("reindexed", file_id=file_id)


def _worker_loop() -> None:
    factory = get_session_factory()
    while not _stop.is_set():
        job_id: int | None = None
        with factory() as db:
            job = db.execute(
                select(Job).where(Job.status == "queued").order_by(Job.priority, Job.id).limit(1)
            ).scalar_one_or_none()
            if job is None:
                db.commit()
            else:
                job.status = "processing"
                job.attempts += 1
                db.commit()
                job_id = job.id
        if job_id is None:
            _stop.wait(0.4)
            continue
        with factory() as db:
            job = db.get(Job, job_id)
            if job is None:
                continue
            try:
                _handle(job)
                job.status = "done"
                job.last_error = None
            except Exception as exc:  # noqa: BLE001
                job.last_error = str(exc)[:1000]
                job.status = "failed" if job.attempts >= 2 else "queued"  # retry 1 раз
                log.warning("job_failed", job_id=job.id, kind=job.kind, error=str(exc))
            db.commit()


def start_worker() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker_loop, name="jobs-worker", daemon=True)
    _thread.start()
    log.info("jobs_worker_started")


def stop_worker() -> None:
    _stop.set()
    log.info("jobs_worker_stopped")


def worker_alive() -> bool:
    """Жив ли поток-воркер очереди (v2.9.1, для админ-диагностики)."""
    return _thread is not None and _thread.is_alive()


def enqueue_reindex(file_id: int) -> int:
    factory = get_session_factory()
    with factory() as db:
        job = Job(file_id=file_id, kind=f"reindex:{file_id}", priority=2)
        db.add(job)
        db.commit()
        return int(job.id)


def enqueue_reprocess_job(file_id: int, actor: str = "admin") -> int:
    """Полная переобработка одного файла из оригинала (v3.0.0, админ-UI)."""
    factory = get_session_factory()
    with factory() as db:
        job = Job(file_id=file_id, kind=f"reprocess:{file_id}", priority=1)
        db.add(job)
        db.commit()
        job_id = int(job.id)
    log_audit(actor, "file_reprocess_enqueued", {"file_id": file_id, "job_id": job_id})
    return job_id


def enqueue_reproduce(file_id: int, target_format: str) -> int:
    factory = get_session_factory()
    with factory() as db:
        job = Job(file_id=file_id, kind=f"reproduce:{target_format}", priority=3)
        db.add(job)
        db.commit()
        return int(job.id)


def job_dir_for(f: File, job_id: int, ext: str) -> Path:
    d = Path(f.stored_path).parent / "reproduced"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job_id}.{ext}"

"""Админ (6.6): очередь задач, переиндексация, метрики, логи, диагностика.
v2.9.1: наблюдаемость ингеста/эмбеддинга (живой прогресс), браузер
документов и чанков, перечень всех моделей агента. Только role=admin.
v3.0.0: CRUD документов/чанков в веб-интерфейсе (удалить/реиндексировать/
править/сохранить), панель «Файлы на диске» (память путей + операции),
пользователи и группы (users.yaml), диагностика — статические фидбэка,
пользователей и путей (право admin => всё)."""
from __future__ import annotations

import json
import platform
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from doc_agent import __version__
from doc_agent.api.routes_status import health_cached
from doc_agent.auth import require_admin, require_perm
from doc_agent.config import _config_file, load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import (
    AuditLog,
    ChatMessage,
    Chunk,
    ContextArchive,
    File,
    FileLocation,
    Job,
    User,
)
from doc_agent.db.session import db_file, get_db
from doc_agent.logging import get_logger
from doc_agent.services import fileops as fileops_service
from doc_agent.services import sorting, users_store
from doc_agent.services.jobs import enqueue_reprocess_job, worker_alive
from doc_agent.vector.chroma_client import get_vector_store, make_chunk_key, vector_degraded, vector_info
from doc_agent.vector.embedder import embed_passages, expected_dim, resolve_backend

log = get_logger("routes.admin")
router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/jobs")
def jobs(limit: int = Query(100, ge=1, le=1000), db=Depends(get_db),
         user: User = Depends(require_admin)) -> dict:
    rows = db.execute(select(Job).order_by(Job.id.desc()).limit(limit)).scalars().all()
    return {"jobs": [
        {"id": j.id, "file_id": j.file_id, "kind": j.kind, "priority": j.priority,
         "status": j.status, "attempts": j.attempts, "last_error": j.last_error,
         "created_at": j.created_at, "updated_at": j.updated_at}
        for j in rows
    ]}


# --- v2.9.1: НАБЛЮДАЕМОСТЬ ИНГЕСТА/ЭМБЕДДИНГА, ДОКУМЕНТЫ+ЧАНКИ, МОДЕЛИ ---


def _parse_ts(value: object | None) -> datetime | None:
    """ISO-строга метки времени (БД) -> datetime; None при сбое."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@router.get("/ingest/progress")
def ingest_progress(db=Depends(get_db), user: User = Depends(require_admin)) -> dict:
    """Живой прогресс обработки файлов (v2.9.1): очередь, текущие задачи,
    последние файлы с числом чанков, темп (файлов/час, сек/файл), недавние
    сбои. Панель «Прогресс эмбеддингинга» опрашивает этот эндпоинт каждые
    chat.status_poll_ms мс. Только БД + вектор, без сетевых вызовов."""
    now = datetime.now(timezone.utc)
    jobs_by_status = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())

    # Текущие (в работе) задачи — с именами файлов и временем старта
    current_rows = db.execute(
        select(Job, File.original_name)
        .join(File, File.id == Job.file_id, isouter=True)
        .where(Job.status == "processing")
        .order_by(Job.id)
    ).all()
    current = []
    for job, name in current_rows:
        started = _parse_ts(job.updated_at)
        current.append({
            "job_id": job.id, "file_id": job.file_id, "kind": job.kind,
            "file_name": name or "-", "attempts": job.attempts,
            "started_at": job.updated_at,
            "elapsed_sec": round((now - started).total_seconds()) if started else None,
        })

    # Последние файлы (любой статус) с числом чанков
    recent_files = db.execute(
        select(File).order_by(File.updated_at.desc()).limit(15)
    ).scalars().all()
    chunk_counts: dict[int, int] = {}
    if recent_files:
        ids = [f.id for f in recent_files]
        rows = db.execute(
            select(Chunk.file_id, func.count()).where(Chunk.file_id.in_(ids))  # noqa: E501
            .group_by(Chunk.file_id)
        ).all()
        chunk_counts = {fid: int(n) for fid, n in rows}

    # Темп: готово за последний час + среднее время файла по последним 20 done
    hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    done_last_hour = db.execute(
        select(func.count()).select_from(Job)
        .where(Job.kind == "ingest", Job.status == "done", Job.updated_at >= hour_ago)
    ).scalar_one()
    done_jobs = db.execute(
        select(Job.created_at, Job.updated_at).where(Job.kind == "ingest", Job.status == "done")
        .order_by(Job.updated_at.desc()).limit(20)
    ).all()
    durations = []
    for created, updated in done_jobs:
        c, u = _parse_ts(created), _parse_ts(updated)
        if c and u and u >= c:
            durations.append((u - c).total_seconds())
    avg_sec = round(sum(durations) / len(durations), 1) if durations else None

    # Недавние сбои (с именами файлов) — видно, ЧТО упало и ПОЧЕМУ
    failed_rows = db.execute(
        select(Job, File.original_name)
        .join(File, File.id == Job.file_id, isouter=True)
        .where(Job.status == "failed")
        .order_by(Job.updated_at.desc()).limit(5)
    ).all()
    failed_recent = [
        {"job_id": job.id, "file_id": job.file_id, "file_name": name or "-",
         "kind": job.kind, "attempts": job.attempts,
         "last_error": (job.last_error or "")[:300], "updated_at": job.updated_at}
        for job, name in failed_rows
    ]

    return {
        "generated_at": utcnow_iso(),
        "version": __version__,
        "worker_alive": worker_alive(),
        "queue": {
            "queued": jobs_by_status.get("queued", 0),
            "processing": jobs_by_status.get("processing", 0),
            "done": jobs_by_status.get("done", 0),
            "failed": jobs_by_status.get("failed", 0),
        },
        "current": current,
        "recent_files": [
            {"id": f.id, "name": f.original_name, "status": f.status,
             "format": f.format, "chunks": chunk_counts.get(f.id, 0),
             "doc_type": f.doc_type or "other", "updated_at": f.updated_at}
            for f in recent_files
        ],
        "throughput": {
            "done_last_hour": int(done_last_hour),
            "avg_sec_per_file": avg_sec,
            "files_done_total": jobs_by_status.get("done", 0),
        },
        "failed_recent": failed_recent,
        "embedding": {
            "resolved_backend": resolve_backend(),
            "model": load_settings().embeddings.model,
            "device": load_settings().embeddings.device or "auto",
            "dim": expected_dim(),
            **vector_info(),
        },
    }


def utcnow_iso() -> str:
    from doc_agent.db.models import utcnow

    return utcnow()


@router.get("/documents")
def documents(status: str | None = Query(None),
              limit: int = Query(200, ge=1, le=1000),
              db=Depends(get_db), user: User = Depends(require_admin)) -> dict:
    """Картотека документов для админ-панели (v2.9.1): последние N файлов
    с числом чанков и статусами. Фильтр по статусу — опционально."""
    files_total = db.execute(select(func.count()).select_from(File)).scalar_one()
    by_status = dict(db.execute(select(File.status, func.count()).group_by(File.status)).all())
    q = select(File).order_by(File.id.desc())
    if status:
        q = q.where(File.status == status)
    rows = db.execute(q.limit(limit)).scalars().all()
    chunk_counts: dict[int, int] = {}
    if rows:
        ids = [f.id for f in rows]
        crows = db.execute(
            select(Chunk.file_id, func.count()).where(Chunk.file_id.in_(ids))  # noqa: E501
            .group_by(Chunk.file_id)
        ).all()
        chunk_counts = {fid: int(n) for fid, n in crows}
    return {
        "files_total": int(files_total),
        "by_status": by_status,
        "files": [
            {"id": f.id, "name": f.original_name, "format": f.format,
             "size_bytes": f.size_bytes, "doc_type": f.doc_type or "other",
             "status": f.status, "chunks": chunk_counts.get(f.id, 0),
             "doc_number": f.doc_number or "", "created_at": f.created_at,
             "updated_at": f.updated_at}
            for f in rows
        ],
    }


@router.get("/documents/{file_id}/chunks")
def document_chunks(file_id: int,
                    limit: int = Query(500, ge=1, le=2000),
                    text_max: int = Query(4000, ge=100, le=20000),
                    db=Depends(get_db), user: User = Depends(require_admin)) -> dict:
    """Чанки одного документа (v2.9.1): то, что реально ушло в векторную
    базу (преамбулы имени/листа/заметки включены). text ограничен text_max
    символами с флагом truncated — чтобы ответ не раздувался на больших
    файлах."""
    f = db.get(File, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    chunks_total = db.execute(
        select(func.count()).select_from(Chunk).where(Chunk.file_id == file_id)
    ).scalar_one()
    rows = db.execute(
        select(Chunk).where(Chunk.file_id == file_id)
        .order_by(Chunk.chunk_index).limit(limit)
    ).scalars().all()
    return {
        "file": {"id": f.id, "name": f.original_name, "status": f.status,
                 "format": f.format, "doc_type": f.doc_type or "other"},
        "chunks_total": int(chunks_total),
        "chunks": [
            {"id": c.id, "chunk_index": c.chunk_index, "page": c.page,
             "char_start": c.char_start, "char_end": c.char_end,
             "chars": len(c.text),
             "truncated": len(c.text) > text_max,
             "text": c.text[:text_max]}
            for c in rows
        ],
    }


def _package_versions() -> dict[str, str]:
    """Версии ключевых пакетов (v2.9.1, для отладки и отчётов)."""
    from importlib.metadata import PackageNotFoundError, version

    wanted = ["fastapi", "uvicorn", "chromadb", "sqlalchemy", "pydantic",
              "httpx", "sentence-transformers", "torch", "transformers",
              "pdfplumber", "openpyxl", "structlog"]
    out: dict[str, str] = {}
    for name in wanted:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "не установлен"
    return out


@router.get("/models")
def models(user: User = Depends(require_admin)) -> dict:  # noqa: ARG001
    """ВСЕ модели, которые использует агент (v2.9.1): LLM (основная/лёгкая/
    планировщик), эмбеддинги (backend/модель/устройство/размерность/префиксы),
    реранкер, OCR, векторное хранилище + версии пакетов."""
    s = load_settings()
    planner_model = s.llm.model_main if s.planner.model == "main" else s.llm.model_light
    return {
        "llm": {
            "provider": s.llm.provider,
            "base_url": s.llm.base_url,
            "api_path": s.llm.api_path,
            "api_key_set": bool(s.llm.api_key),
            "model_main": s.llm.model_main,
            "model_light": s.llm.model_light,
            "planner_enabled": s.planner.enabled,
            "planner_config": s.planner.model,
            "planner_model": planner_model,
            "temperature": s.llm.temperature,
            "timeout_sec": s.llm.timeout_sec,
            "rate_limit_retries": s.llm.rate_limit_retries,
        },
        "embeddings": {
            "backend": s.embeddings.backend,
            "resolved_backend": resolve_backend(),
            "model": s.embeddings.model,
            "device": s.embeddings.device or "auto",
            "dimensions": s.embeddings.dimensions if s.embeddings.dimensions > 0
            else "auto (из модели)",
            "query_prefix": s.embeddings.query_prefix,
            "passage_prefix": s.embeddings.passage_prefix,
            "batch_size": s.embeddings.batch_size,
            "api_model": s.embeddings.api.model,
            "api_base_url": s.embeddings.api.base_url or f"{s.llm.base_url} (из llm)",
            "api_dimensions": s.embeddings.api.dimensions or "auto",
        },
        "vector": {**vector_info(),
                   "metric": s.vector.metric,
                   "auto_collection_suffix": s.vector.auto_collection_suffix},
        "reranker": {"backend": s.reranker.backend, "model": s.reranker.model,
                     "top_k": s.reranker.top_k},
        "ocr": {"engine": s.ocr.engine, "langs": s.ocr.tesseract_langs,
                "min_confidence": s.ocr.min_confidence},
        "packages": _package_versions(),
    }


@router.post("/reindex")
def reindex(db=Depends(get_db), user: User = Depends(require_admin)) -> dict:
    from doc_agent.db.models import Job as JobModel
    from doc_agent.services.jobs import enqueue_reproduce  # noqa: F401

    job = JobModel(file_id=None, kind="reindex_all", priority=2)
    db.add(job)
    db.commit()
    return {"job_id": job.id, "message": "Полная переиндексация поставлена в очередь"}


@router.get("/metrics")
def metrics(db=Depends(get_db), user: User = Depends(require_admin)) -> dict:
    files_total = db.execute(select(func.count()).select_from(File)).scalar_one()
    by_status = dict(db.execute(select(File.status, func.count()).group_by(File.status)).all())
    queries = db.execute(
        select(AuditLog).where(AuditLog.action == "query_answered").order_by(AuditLog.id.desc()).limit(500)
    ).scalars().all()
    total_q = len(queries)
    grounded = partial = no_data = 0
    for entry in queries:
        try:
            payload = json.loads(entry.payload or "{}")
        except json.JSONDecodeError:
            continue
        grounded += bool(payload.get("grounded"))
        partial += bool(payload.get("partial"))
        no_data += bool(payload.get("no_data"))
    return {
        "files_total": files_total,
        "files_by_status": by_status,
        "queries_total": total_q,
        "grounded_ratio": round(grounded / total_q, 3) if total_q else 1.0,
        "partial_ratio": round(partial / total_q, 3) if total_q else 0.0,
        "no_data_ratio": round(no_data / total_q, 3) if total_q else 0.0,
        "vector": vector_info(),
        "vector_degraded": vector_degraded(),
    }


@router.get("/logs")
def logs(tail: int = Query(200, ge=1, le=2000), user: User = Depends(require_admin)) -> dict:
    settings = load_settings()
    log_file = settings.app.sub_dir("logs") / "app.log"
    if not log_file.exists():
        return {"lines": []}
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"lines": lines[-tail:]}


def _is_problem_line(line: str) -> bool:
    """Строка лога с уровнем error/warning (structlog JSON или текст)."""
    try:
        return json.loads(line).get("level") in ("error", "warning")
    except (json.JSONDecodeError, ValueError, AttributeError):
        low = line.lower()
        return "error" in low or "warning" in low


def _error_tail(limit: int) -> list[str]:
    """Последние ошибки/предупреждения из app.log (для отчёта разработчику)."""
    log_file = load_settings().app.sub_dir("logs") / "app.log"
    if not log_file.exists():
        return []
    out: list[str] = []
    for line in reversed(log_file.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not line.strip() or not _is_problem_line(line):
            continue
        out.append(line)
        if len(out) >= limit:
            break
    return list(reversed(out))


@router.get("/debug")
def debug(db=Depends(get_db), user: User = Depends(require_admin)) -> dict:
    """Диагностика для отчёта разработчику: статус модели, БД, вектора,
    очередь, задания разгребания, последние ошибки. Показывается в
    /admin-ui с кнопкой «Скопировать»."""
    from doc_agent.db.models import utcnow

    s = load_settings()
    files_total = db.execute(select(func.count()).select_from(File)).scalar_one()
    chunks_total = db.execute(select(func.count()).select_from(Chunk)).scalar_one()
    jobs_by_status = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    chat_messages = db.execute(select(func.count()).select_from(ChatMessage)).scalar_one()
    chat_active = db.execute(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.active == 1)
    ).scalar_one()
    archives_total = db.execute(select(func.count()).select_from(ContextArchive)).scalar_one()
    audit_rows = db.execute(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(s.chat.debug_audit_tail)
    ).scalars().all()
    db_path = db_file()
    return {
        "generated_at": utcnow(),
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "config_file": str(_config_file()),
        "data_dir": str(s.app.data_path),
        "health": health_cached(),
        "llm": {
            "provider": s.llm.provider, "base_url": s.llm.base_url,
            "api_path": s.llm.api_path, "model_main": s.llm.model_main,
            "model_light": s.llm.model_light, "api_key_set": bool(s.llm.api_key),
            "timeout_sec": s.llm.timeout_sec, "temperature": s.llm.temperature,
        },
        "embeddings": {
            "backend": s.embeddings.backend,
            "resolved_backend": resolve_backend(),
            "model": s.embeddings.model,
            # v2.9: параметры ЛОКАЛЬНОЙ модели — устройство, размерность,
            # префиксы E5 (важны для качества поиска e5-моделей).
            "device": s.embeddings.device or "auto",
            "local_dimensions": s.embeddings.dimensions if s.embeddings.dimensions > 0
            else "auto (из модели)",
            "query_prefix": s.embeddings.query_prefix,
            "api_model": s.embeddings.api.model,
            # v2.7.1: видно, куда реально пойдут эмбеддинги и какая
            # размерность (пустые base_url/api_key = наследование из llm).
            "api_base_url": s.embeddings.api.base_url or f"{s.llm.base_url} (из llm)",
            "api_key_set": bool(s.embeddings.api.api_key or s.llm.api_key),
            "dimensions": s.embeddings.api.dimensions or "auto",
        },
        "vector": vector_info(),
        "vector_degraded": vector_degraded(),
        "database": {
            "file": str(db_path),
            "size_mb": round(db_path.stat().st_size / (1024 * 1024), 2) if db_path.exists() else 0,
            "files_total": int(files_total),
            "chunks_total": int(chunks_total),
            "jobs_by_status": jobs_by_status,
            "chat_messages": int(chat_messages),
            "chat_active_context": int(chat_active),
            "context_archives": int(archives_total),
        },
        "sort_jobs": sorting.list_jobs(),
        "audit_tail": [
            {"ts": a.created_at, "actor": a.actor, "action": a.action,
             "payload": (a.payload or "")[:200]}
            for a in audit_rows
        ],
        "error_log_tail": _error_tail(s.chat.debug_log_tail),
        # v2.9.1: доп. отладочная информация — версии пакетов, воркер очереди,
        # реранкер/OCR (раньше их не было видно в отчёте разработчику).
        "packages": _package_versions(),
        "worker_alive": worker_alive(),
        "reranker": {"backend": s.reranker.backend, "model": s.reranker.model,
                     "top_k": s.reranker.top_k},
        "ocr": {"engine": s.ocr.engine, "langs": s.ocr.tesseract_langs},
        # v3.0.0: фидбэк, пользователи/группы, файлы на диске
        "feedback": feedback_stats(),
        "users_file": {
            "path": str(users_store.users_file()),
            "exists": users_store.users_file().exists(),
            "users": len(users_store.load().get("users", [])),
            "groups": list(users_store.load().get("groups", {}).keys()),
        },
        "file_locations_total": int(db.execute(
            select(func.count()).select_from(FileLocation)).scalar_one()),
        "file_ops_allowed_roots": s.files.allowed_roots,
    }


def feedback_stats() -> dict:
    """Статистика обратной связи для диагностики (без выбросов при сбое БД)."""
    try:
        from doc_agent.services import feedback as feedback_service

        return feedback_service.stats()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# ======================================================================
# v3.0.0: CRUD ДОКУМЕНТОВ И ЧАНКОВ ПРЯМО В ВЕБ-ИНТЕРФЕЙСЕ
# (запрос: «у Админа должна быть возможность администрировать чанки и
#  документы: удалить, проиндексировать, отредактировать, сохранить»)
# ======================================================================

@router.delete("/documents/{file_id}")
def delete_document(file_id: int, db=Depends(get_db),
                    user: User = Depends(require_perm("documents_manage"))) -> dict:
    """Удалить документ целиком: чанки + векторы + запись File + пути."""
    f = db.get(File, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    name = f.original_name
    chunks = db.execute(select(func.count()).select_from(Chunk)
                        .where(Chunk.file_id == file_id)).scalar_one()
    try:
        get_vector_store().delete_file(file_id)
    except Exception as exc:  # noqa: BLE001 — вектор может быть недоступен
        log.warning("document_delete_vector_failed", file_id=file_id, error=str(exc))
    db.delete(f)  # chunks/locations/jobs удалятся каскадом (FK ondelete)
    db.commit()
    log_audit(user.username or "admin", "document_deleted",
              {"file_id": file_id, "name": name, "chunks": int(chunks)})
    log.info("document_deleted", file_id=file_id, name=name, chunks=int(chunks))
    return {"ok": True, "deleted": file_id, "chunks_removed": int(chunks),
            "message": f"Документ «{name}» удалён вместе с чанками и векторами"}


@router.post("/documents/{file_id}/reprocess")
def reprocess_document(file_id: int, db=Depends(get_db),
                       user: User = Depends(require_perm("documents_manage"))) -> dict:
    """Полная переобработка файла из оригинала (извлечение + чанки +
    эмбеддинги с ТЕКУЩИМИ настройками). Задача ставится в очередь."""
    f = db.get(File, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    job_id = enqueue_reprocess_job(file_id, actor=user.username or "admin")
    return {"job_id": job_id, "message": f"Переобработка «{f.original_name}» поставлена в очередь"}


class ChunkUpdate(BaseModel):
    text: str


@router.put("/chunks/{chunk_id}")
def update_chunk(chunk_id: int, body: ChunkUpdate, db=Depends(get_db),
                 user: User = Depends(require_perm("documents_manage"))) -> dict:
    """Отредактировать текст чанка и СОХРАНИТЬ: БД + переэмбеддинг чанка
    в векторной базе (чтобы поиск сразу находил исправленное)."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Текст чанка пуст")
    c = db.get(Chunk, chunk_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Чанк не найден")
    f = db.get(File, c.file_id)
    old_len = len(c.text)
    c.text = text[:200000]
    db.commit()
    # переэмбеддинг одного чанка — дёшево (e5-small: ~миллисекунды на чанк)
    try:
        embeddings = embed_passages([c.text])
        get_vector_store().upsert_chunks(
            ids=[make_chunk_key(c.file_id, c.chunk_index)],
            embeddings=embeddings,
            documents=[c.text],
            metadatas=[{
                "file_id": c.file_id, "chunk_index": c.chunk_index,
                "page": c.page or 1, "doc_type": (f.doc_type if f else None) or "other",
                "contract_no": (f.contract_no if f else "") or "",
                "city": (f.city if f else "") or "",
            }],
        )
    except Exception as exc:  # noqa: BLE001 — текст сохранён, вектор обновить не удалось
        log.warning("chunk_reembed_failed", chunk_id=chunk_id, error=str(exc))
        return {"ok": True, "chunk_id": chunk_id, "chars_before": old_len, "chars_after": len(c.text),
                "vector_updated": False,
                "message": "Текст сохранён, но вектор не обновлён — запустите «Переиндексация»"}
    log_audit(user.username or "admin", "chunk_updated",
              {"chunk_id": chunk_id, "file_id": c.file_id, "chars": len(c.text)})
    return {"ok": True, "chunk_id": chunk_id, "chars_before": old_len,
            "chars_after": len(c.text), "vector_updated": True,
            "message": "Чанк сохранён и переэмбеддирован"}


@router.delete("/chunks/{chunk_id}")
def delete_chunk(chunk_id: int, db=Depends(get_db),
                 user: User = Depends(require_perm("documents_manage"))) -> dict:
    """Удалить чанк из БД и векторной базы (искажённый OCR, мусор и т.п.)."""
    c = db.get(Chunk, chunk_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Чанк не найден")
    key = make_chunk_key(c.file_id, c.chunk_index)
    db.delete(c)
    db.commit()
    try:
        store = get_vector_store()
        if hasattr(store, "delete_chunks"):
            store.delete_chunks([key])
    except Exception as exc:  # noqa: BLE001
        log.warning("chunk_vector_delete_failed", chunk_id=chunk_id, error=str(exc))
    log_audit(user.username or "admin", "chunk_deleted",
              {"chunk_id": chunk_id, "file_id": c.file_id})
    return {"ok": True, "deleted": chunk_id, "message": "Чанк удалён из БД и векторной базы"}


# ======================================================================
# v3.0.0: ФАЙЛЫ НА ДИСКЕ — память путей + операции (админ-вкладка)
# ======================================================================

@router.get("/file-locations")
def file_locations(limit: int = Query(500, ge=1, le=2000), db=Depends(get_db),
                   user: User = Depends(require_admin)) -> dict:
    rows = db.execute(
        select(FileLocation, File.original_name)
        .join(File, File.id == FileLocation.file_id, isouter=True)
        .order_by(FileLocation.is_current.desc(), FileLocation.id.desc())
        .limit(limit)
    ).all()
    total = db.execute(select(func.count()).select_from(FileLocation)).scalar_one()
    return {
        "total": int(total),
        "allowed_roots_config": load_settings().files.allowed_roots,
        "items": [
            {"id": loc.id, "file_id": loc.file_id, "file_name": name or "-",
             "path": loc.path, "kind": loc.kind, "is_current": bool(loc.is_current),
             "exists": Path(loc.path).exists(),
             "created_at": loc.created_at}
            for loc, name in rows
        ],
    }


class LocationCreate(BaseModel):
    file_id: int
    path: str


@router.post("/file-locations")
def create_location(body: LocationCreate, db=Depends(get_db),
                    user: User = Depends(require_admin)) -> dict:
    """Запомнить путь вручную (например, файл загружен через браузер)."""
    f = db.get(File, body.file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    p = Path(body.path).expanduser()
    if not p.exists():
        raise HTTPException(status_code=422, detail=f"Путь не существует: {p}")
    fileops_service.remember(body.file_id, str(p), kind="manual",
                             actor=user.username or "admin")
    log_audit(user.username or "admin", "file_location_added",
              {"file_id": body.file_id, "path": str(p)})
    return {"ok": True, "file_id": body.file_id, "path": str(p),
            "message": "Путь запомнен"}


@router.delete("/file-locations/{loc_id}")
def delete_location(loc_id: int, db=Depends(get_db),
                    user: User = Depends(require_admin)) -> dict:
    loc = db.get(FileLocation, loc_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(loc)
    db.commit()
    log_audit(user.username or "admin", "file_location_deleted", {"id": loc_id})
    return {"ok": True, "deleted": loc_id}


class FileOpRequest(BaseModel):
    dest: str
    create_dest: bool = True


@router.post("/files/{file_id}/move")
def admin_move_file(file_id: int, body: FileOpRequest,
                    user: User = Depends(require_perm("files_manage"))) -> dict:
    try:
        out = fileops_service.move_file(file_id, body.dest, user.username or "admin",
                                        body.create_dest)
    except fileops_service.FileOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **out}


@router.post("/files/{file_id}/copy")
def admin_copy_file(file_id: int, body: FileOpRequest,
                    user: User = Depends(require_perm("files_manage"))) -> dict:
    try:
        out = fileops_service.copy_file(file_id, body.dest, user.username or "admin",
                                        body.create_dest)
    except fileops_service.FileOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **out}


class MkdirRequest(BaseModel):
    path: str


@router.post("/files/mkdir")
def admin_mkdir(body: MkdirRequest,
                user: User = Depends(require_perm("files_manage"))) -> dict:
    """Создать папку внутри разрешённых корней (панель «Файлы на диске»)."""
    try:
        target = fileops_service.make_dir(body.path, user.username or "admin")
    except fileops_service.FileOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(target)}


# ======================================================================
# v3.0.0: ПОЛЬЗОВАТЕЛИ И ГРУППЫ (users.yaml — отдельный бэкап-файл)
# ======================================================================

@router.get("/users")
def users_overview(user: User = Depends(require_perm("users_manage"))) -> dict:
    return users_store.snapshot_for_admin()


class UserCreate(BaseModel):
    username: str
    password: str
    groups: list[str] = Field(default_factory=lambda: ["users"])
    display_name: str = ""


class UserUpdate(BaseModel):
    password: str | None = None
    groups: list[str] | None = None
    display_name: str | None = None
    is_active: bool | None = None


@router.post("/users")
def users_create(body: UserCreate,
                 user: User = Depends(require_perm("users_manage"))) -> dict:
    try:
        entry = users_store.create_user(body.username, body.password, body.groups,
                                        body.display_name, actor=user.username or "admin")
    except users_store.UsersError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "user": entry}


@router.put("/users/{username}")
def users_update(username: str, body: UserUpdate,
                 user: User = Depends(require_perm("users_manage"))) -> dict:
    try:
        entry = users_store.update_user(
            username, password=body.password, groups=body.groups,
            display_name=body.display_name, is_active=body.is_active,
            actor=user.username or "admin")
    except users_store.UsersError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "user": entry}


@router.delete("/users/{username}")
def users_delete(username: str, user: User = Depends(require_perm("users_manage"))) -> dict:
    if users_store.get_entry(username) is None:
        raise HTTPException(status_code=404, detail=f"Пользователь не найден: {username}")
    try:
        users_store.delete_user(username, actor=user.username or "admin")
    except users_store.UsersError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "deleted": username}


class GroupSave(BaseModel):
    permissions: list[str]
    allowed_roots: list[str] = []


@router.post("/groups/{name}")
def groups_save(name: str, body: GroupSave,
                user: User = Depends(require_perm("users_manage"))) -> dict:
    try:
        out = users_store.upsert_group(name, body.permissions, body.allowed_roots,
                                       actor=user.username or "admin")
    except users_store.UsersError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "group": name, **out}


@router.delete("/groups/{name}")
def groups_delete(name: str, user: User = Depends(require_perm("users_manage"))) -> dict:
    try:
        users_store.delete_group(name, actor=user.username or "admin")
    except users_store.UsersError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "deleted": name}

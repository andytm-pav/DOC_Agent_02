"""Админ (6.6): очередь задач, переиндексация, метрики, логи, диагностика.
Только role=admin."""
from __future__ import annotations

import json
import platform

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from doc_agent import __version__
from doc_agent.api.routes_status import health_cached
from doc_agent.auth import require_admin
from doc_agent.config import _config_file, load_settings
from doc_agent.db.models import AuditLog, ChatMessage, Chunk, ContextArchive, File, Job, User
from doc_agent.db.session import db_file, get_db
from doc_agent.logging import get_logger
from doc_agent.services import sorting
from doc_agent.vector.chroma_client import vector_degraded, vector_info

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
        "embeddings": {"backend": s.embeddings.backend, "model": s.embeddings.model},
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
    }

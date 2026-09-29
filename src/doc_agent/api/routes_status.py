"""Статус агента для строки в UI: GET /status (любой авторизованный).

Всегда видно, что делает агент: состояние модели/БД/вектора, очередь
обработки файлов, фазы разгребания свалки, счётчики чата. Проверка
здоровья кэшируется на chat.health_cache_sec — строка статуса опрашивается
часто, а сетевые проверки LLM — нет.
"""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from doc_agent import __version__
from doc_agent.auth import get_current_user
from doc_agent.config import load_settings
from doc_agent.db.models import AuditLog, ChatMessage, ContextArchive, File, Job, User
from doc_agent.db.session import check_db, get_db
from doc_agent.llm.ollama_client import llm_healthy
from doc_agent.services import sorting
from doc_agent.vector.chroma_client import get_vector_store, vector_degraded

router = APIRouter(tags=["status"])

_health_lock = threading.Lock()
_health_at: float = 0.0
_health_data: dict | None = None


def _collect_health() -> dict:
    db_ok = check_db()
    try:
        chroma_ok = get_vector_store().healthy() and not vector_degraded()
    except Exception:  # noqa: BLE001
        chroma_ok = False
    try:
        llm_ok = llm_healthy()
    except Exception:  # noqa: BLE001
        llm_ok = False
    return {
        "db": "ok" if db_ok else "fail",
        "chroma": "ok" if chroma_ok else "fail",
        "llm": "ok" if llm_ok else "fail",
    }


def health_cached() -> dict:
    """Состояние БД/вектора/LLM с кэшем chat.health_cache_sec."""
    global _health_at, _health_data
    ttl = load_settings().chat.health_cache_sec
    with _health_lock:
        if _health_data is not None and time.monotonic() - _health_at < ttl:
            return _health_data
    data = _collect_health()
    with _health_lock:
        _health_at = time.monotonic()
        _health_data = data
    return data


@router.get("/status")
def status(db=Depends(get_db), user: User = Depends(get_current_user)) -> dict:  # noqa: ARG001
    s = load_settings()
    queue = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    files_processing = db.execute(
        select(func.count()).select_from(File).where(File.status == "processing")
    ).scalar_one()
    messages = db.execute(select(func.count()).select_from(ChatMessage)).scalar_one()
    active = db.execute(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.active == 1)
    ).scalar_one()
    archives = db.execute(select(func.count()).select_from(ContextArchive)).scalar_one()
    last_actions = db.execute(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(5)
    ).scalars().all()
    return {
        "version": __version__,
        "health": health_cached(),
        "llm": {
            "provider": s.llm.provider,
            "base_url": s.llm.base_url,
            "model_main": s.llm.model_main,
            "model_light": s.llm.model_light,
            "api_key_set": bool(s.llm.api_key),
        },
        "activity": {
            "queue": queue,
            "files_processing": int(files_processing),
            "sort_jobs": sorting.list_jobs(),
        },
        "chat": {
            "messages": int(messages),
            "active_context": int(active),
            "archives": int(archives),
        },
        "last_actions": [
            {"ts": a.created_at, "actor": a.actor, "action": a.action} for a in last_actions
        ],
    }

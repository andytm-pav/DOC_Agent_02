"""Ручные миграции: создание таблиц + администратор по умолчанию."""
from __future__ import annotations

import json

from passlib.context import CryptContext
from sqlalchemy import select

from doc_agent.config import load_settings
from doc_agent.db.models import AuditLog, Base, User
from doc_agent.db.session import get_engine, get_session_factory
from doc_agent.logging import get_logger

log = get_logger("db.migrations")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except Exception:  # noqa: BLE001
        return False


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    settings = load_settings()
    factory = get_session_factory()
    with factory() as session:
        admin_name = settings.app.admin_username or "admin"
        existing = session.execute(select(User).where(User.username == admin_name)).scalar_one_or_none()
        if existing is None:
            session.add(
                User(
                    username=admin_name,
                    password_hash=hash_password(settings.app.admin_password or "admin"),
                    role="admin",
                )
            )
            session.add(
                AuditLog(actor="system", action="db_init", payload=json.dumps({"admin": admin_name}))
            )
            session.commit()
            log.info("db_initialized", admin=admin_name)


def log_audit(actor: str, action: str, payload: dict | None = None) -> None:
    """Единая точка записи audit_log (раздел 10 ТЗ)."""
    factory = get_session_factory()
    with factory() as session:
        session.add(AuditLog(actor=actor, action=action, payload=json.dumps(payload or {}, ensure_ascii=False)))
        session.commit()

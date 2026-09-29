"""Сессии SQLAlchemy + движок SQLite (WAL, foreign_keys=ON)."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from doc_agent.config import load_settings

_engines: dict[str, Engine] = {}
_factories: dict[str, sessionmaker[Session]] = {}


def db_file() -> Path:
    s = load_settings()
    return s.app.sub_dir("sqlite") / "app.db"


def get_engine() -> Engine:
    url = f"sqlite:///{db_file()}"
    if url in _engines:
        return _engines[url]
    engine = create_engine(url, connect_args={"check_same_thread": False}, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: object, _rec: object) -> None:  # pragma: no cover
        cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    _engines[url] = engine
    _factories[url] = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    return _factories[f"sqlite:///{db_file()}"]


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_db() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False

"""FastAPI app + lifespan (Шаг 4/18 ТЗ)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from doc_agent import __version__
from doc_agent.api import (
    routes_a2a,
    routes_admin,
    routes_auth,
    routes_card,
    routes_chat,
    routes_feedback,
    routes_files,
    routes_query,
    routes_status,
    routes_ui,
)
from doc_agent.config import REPO_ROOT, load_settings
from doc_agent.db.migrations import init_db
from doc_agent.db.session import check_db
from doc_agent.llm.ollama_client import llm_healthy
from doc_agent.logging import get_logger, setup_logging
from doc_agent.services import users_store
from doc_agent.services.jobs import start_worker, stop_worker
from doc_agent.services.watcher import start_watcher, stop_watcher
from doc_agent.vector.chroma_client import get_vector_store, vector_degraded

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = load_settings()
    settings.app.sub_dir(settings.app.storage_subdir)
    settings.app.sub_dir("sqlite")
    settings.app.sub_dir("chroma")
    settings.app.sub_dir("logs")
    settings.app.sub_dir("inbox")
    init_db()
    # v3.0.0: пользователи/группы в отдельном файле (users.yaml) — создаётся
    # при первом старте, SQLite-пользователи переносятся (bcrypt совместим)
    try:
        users_store.ensure_users_file()
    except Exception as exc:  # noqa: BLE001 — старт не должен падать из-за файла
        log.warning("users_file_ensure_failed", error=str(exc))
    get_vector_store()
    start_worker()
    start_watcher()
    log.info("startup_ok", port=settings.app.port, llm_provider=settings.llm.provider)
    yield
    stop_watcher()
    stop_worker()
    log.info("shutdown_ok")


app = FastAPI(title="Документовед", version=__version__, lifespan=lifespan)

app.include_router(routes_auth.router)
app.include_router(routes_files.router)
app.include_router(routes_card.router)
app.include_router(routes_query.router)
app.include_router(routes_chat.router)
app.include_router(routes_feedback.router)
app.include_router(routes_status.router)
app.include_router(routes_admin.router)
app.include_router(routes_a2a.router)
app.include_router(routes_ui.router)

static_dir = REPO_ROOT / "src" / "doc_agent" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
def health() -> dict:
    """6.8: db, chroma, llm (ключ ollama в ответе сохранён по контракту)."""
    db_ok = check_db()
    try:
        chroma_ok = get_vector_store().healthy() and not vector_degraded()
    except Exception:  # noqa: BLE001
        chroma_ok = False
    try:
        llm_ok = llm_healthy()
    except Exception:  # noqa: BLE001
        llm_ok = False
    degraded = not (db_ok and chroma_ok and llm_ok)
    return {
        "status": "degraded" if degraded else "ok",
        "db": "ok" if db_ok else "fail",
        "chroma": "ok" if chroma_ok else "degraded",
        "ollama": "ok" if llm_ok else "degraded",
    }


if __name__ == "__main__":
    # Запуск из PyCharm: правый клик на main.py -> Run (рабочая папка — корень проекта)
    import uvicorn

    s = load_settings()
    uvicorn.run("doc_agent.main:app", host=s.app.host, port=s.app.port, reload=False)

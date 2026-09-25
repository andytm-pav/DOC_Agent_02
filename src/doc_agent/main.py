"""FastAPI application with lifespan management."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from doc_agent.config import get_settings
from doc_agent.db.session import init_db
from doc_agent.logging import setup_logging

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown."""
    settings = get_settings()
    setup_logging()
    logger.info("Starting Документовед", version="2.0.0")

    # Initialize database
    init_db(settings.data_dir)
    logger.info("Database initialized")

    # Ensure storage directories exist
    storage_path = Path(settings.data_dir) / "storage"
    storage_path.mkdir(parents=True, exist_ok=True)

    yield

    logger.info("Shutting down Документовед")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Документовед",
        description="Локальный ИИ-агент для работы с документами",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Setup templates
    templates_dir = Path(__file__).parent / "templates"
    app.state.templates = Jinja2Templates(directory=str(templates_dir))

    # Register routes
    from doc_agent.api import routes_auth, routes_files, routes_query, routes_admin, routes_a2a, routes_ui
    app.include_router(routes_ui.router)
    app.include_router(routes_auth.router, prefix="/auth", tags=["auth"])
    app.include_router(routes_files.router, prefix="/files", tags=["files"])
    app.include_router(routes_query.router, prefix="/query", tags=["query"])
    app.include_router(routes_admin.router, prefix="/admin", tags=["admin"])
    app.include_router(routes_a2a.router, tags=["a2a"])

    # Health endpoint
    @app.get("/health", tags=["health"])
    async def health() -> dict:
        """Health check endpoint."""
        from doc_agent.db.session import check_db
        from doc_agent.vector.chroma_client import check_chroma
        from doc_agent.llm.ollama_client import check_ollama

        db_status = "ok" if check_db() else "error"
        chroma_status = "ok" if check_chroma() else "error"
        ollama_status = "ok" if check_ollama() else "error"

        overall = "ok" if all(s == "ok" for s in [db_status, chroma_status, ollama_status]) else "degraded"

        return {
            "status": overall,
            "db": db_status,
            "chroma": chroma_status,
            "ollama": ollama_status,
        }

    return app


app = create_app()

"""UI: GET / (чат), GET /admin-ui, GET /login (6.x + Jinja2 + htmx локально)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from doc_agent.config import REPO_ROOT, load_settings

router = APIRouter(tags=["ui"])

templates = Jinja2Templates(directory=str(REPO_ROOT / "src" / "doc_agent" / "templates"))


@router.get("/", response_class=HTMLResponse)
def chat_page(request: Request) -> HTMLResponse:
    cfg = load_settings()
    # Папка свалки из конфига подставляется в поле «Импорт из папки».
    default_folder = cfg.ingest.folder_paths[0] if cfg.ingest.folder_paths else ""
    return templates.TemplateResponse(
        request, "chat.html",
        {"title": "Документовед — Чат", "default_folder": default_folder,
         "sort_poll_ms": cfg.sorting.poll_interval_ms,
         "status_poll_ms": cfg.chat.status_poll_ms},
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"title": "Вход — Документовед"})


@router.get("/admin-ui", response_class=HTMLResponse)
def admin_page(request: Request) -> HTMLResponse:
    cfg = load_settings()
    # v2.9.1: панель «Прогресс эмбеддингинга» опрашивается с тем же
    # интервалом из конфига, что и строка статуса (chat.status_poll_ms).
    return templates.TemplateResponse(
        request, "admin.html",
        {"title": "Админ — Документовед", "status_poll_ms": cfg.chat.status_poll_ms},
    )

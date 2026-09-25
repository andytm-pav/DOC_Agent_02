"""UI routes serving HTML templates."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the main chat page."""
    templates = request.app.state.templates
    return templates.TemplateResponse("chat.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Serve the login page."""
    templates = request.app.state.templates
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    """Serve the admin page."""
    templates = request.app.state.templates
    return templates.TemplateResponse("admin.html", {"request": request})

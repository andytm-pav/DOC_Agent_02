"""A2A (6.7): GET /.well-known/agent.json, POST /a2a (JSON-RPC 2.0)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from doc_agent.auth import get_current_user_optional
from doc_agent.config import load_settings
from doc_agent.db.models import User
from doc_agent.services.a2a_server import agent_card, handle_rpc

router = APIRouter(tags=["a2a"])


@router.get("/.well-known/agent.json")
def well_known(request: Request) -> dict:
    base_url = str(request.base_url).rstrip("/")
    return agent_card(base_url)


class A2ARequest(BaseModel):
    model_config = {"extra": "allow"}
    jsonrpc: str = "2.0"
    method: str = ""
    id: str | int | None = None
    params: dict | None = None


@router.post("/a2a")
def a2a(body: dict, user: User = Depends(get_current_user_optional)) -> dict:
    s = load_settings()
    if s.a2a.auth_required and user.username == "a2a-client":
        return {"jsonrpc": "2.0", "id": body.get("id"),
                "error": {"code": -32001, "message": "Требуется JWT (a2a.auth_required=true)"}}
    return handle_rpc(body)

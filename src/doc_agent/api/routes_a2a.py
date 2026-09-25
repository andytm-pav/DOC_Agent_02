"""A2A (Agent-to-Agent) protocol routes."""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

from doc_agent.services.a2a_server import get_agent_card, handle_a2a_request

router = APIRouter()


class A2ARequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    id: str | int
    params: dict[str, Any]


class A2AResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


@router.get("/.well-known/agent.json")
async def agent_card() -> dict:
    """Return the Agent Card for A2A discovery."""
    return get_agent_card()


@router.post("/a2a", response_model=A2AResponse)
async def a2a_endpoint(req: A2ARequest) -> A2AResponse:
    """Handle A2A JSON-RPC requests."""
    if req.method != "tasks/send":
        return A2AResponse(
            jsonrpc="2.0",
            id=req.id,
            error={"code": -32601, "message": "Method not found"},
        )

    try:
        result = await handle_a2a_request(req.params)
        return A2AResponse(
            jsonrpc="2.0",
            id=req.id,
            result=result,
        )
    except Exception as e:
        return A2AResponse(
            jsonrpc="2.0",
            id=req.id,
            error={"code": -32000, "message": str(e)},
        )

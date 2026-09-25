"""A2A (Agent-to-Agent) server."""

from typing import Any

from doc_agent.config import get_settings
from doc_agent.services.query import query_documents


def get_agent_card() -> dict[str, Any]:
    """Return the Agent Card for A2A discovery."""
    settings = get_settings()
    return {
        "name": settings.a2a_agent_name,
        "description": "Локальный ИИ-агент «Документовед» для работы с документами",
        "version": "2.0.0",
        "capabilities": {
            "query": True,
            "ingest": True,
            "export": True,
        },
        "protocols": ["a2a/0.2"],
    }


async def handle_a2a_request(params: dict[str, Any]) -> dict[str, Any]:
    """Handle an A2A JSON-RPC request."""
    message = params.get("message", {})
    parts = message.get("parts", [])

    # Extract text from parts
    text = ""
    for part in parts:
        if part.get("type") == "text":
            text = part.get("text", "")

    if not text:
        return {
            "status": "failed",
            "error": "No text in message",
        }

    # Process query
    result = await query_documents(text)

    return {
        "status": "completed",
        "artifacts": [
            {
                "parts": [
                    {"type": "text", "text": result["answer"]},
                    {"type": "data", "data": {"files": result["files"]}},
                ]
            }
        ],
    }

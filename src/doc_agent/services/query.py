"""Query service."""

from typing import Any

from doc_agent.subagents.orchestrator import Orchestrator


async def query_documents(question: str, limit: int = 20) -> dict[str, Any]:
    """Query documents and return an answer."""
    orchestrator = Orchestrator()
    return await orchestrator.query(question, limit)

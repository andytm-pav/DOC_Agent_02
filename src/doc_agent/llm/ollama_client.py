"""Ollama HTTP client."""

import httpx
import structlog

from doc_agent.config import get_settings

logger = structlog.get_logger()


async def generate(prompt: str, model_type: str = "main") -> str:
    """Generate text using Ollama."""
    settings = get_settings()
    model = settings.model_main if model_type == "main" else settings.model_light

    async with httpx.AsyncClient(timeout=settings.llm_timeout_sec) as client:
        response = await client.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")


async def chat(messages: list[dict[str, str]], model_type: str = "main") -> str:
    """Chat with Ollama using the chat API."""
    settings = get_settings()
    model = settings.model_main if model_type == "main" else settings.model_light

    async with httpx.AsyncClient(timeout=settings.llm_timeout_sec) as client:
        response = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "")


def check_ollama() -> bool:
    """Check if Ollama is accessible."""
    try:
        settings = get_settings()
        response = httpx.get(f"{settings.ollama_url}/api/tags", timeout=5)
        return response.status_code == 200
    except Exception:
        return False

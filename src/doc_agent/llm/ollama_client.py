"""LLM-клиенты.

- OllamaClient        — локальный Ollama (офлайн-режим ТЗ).
- OpenAICompatible    — ЛЮБАЯ внешняя модель по API с ключом
                        (OpenAI / OpenRouter / Z.ai / LM Studio и т.п.).
Выбор провайдера — только через config/config.yaml: llm.provider.
"""
from __future__ import annotations

from typing import Any, Protocol

import httpx

from doc_agent.config import LLMSettings, load_settings
from doc_agent.logging import get_logger

log = get_logger("llm.client")


class LLMClient(Protocol):
    def chat(self, prompt: str, model: str | None = None, timeout: float | None = None) -> str: ...
    def ping(self) -> bool: ...


class OllamaClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.s = settings

    def chat(self, prompt: str, model: str | None = None, timeout: float | None = None) -> str:
        url = self.s.base_url.rstrip("/") + "/api/chat"
        payload = {
            "model": model or self.s.model_main,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": self.s.temperature},
        }
        r = httpx.post(url, json=payload, timeout=timeout or self.s.timeout_sec)
        r.raise_for_status()
        data = r.json()
        return str(data.get("message", {}).get("content", ""))

    def ping(self) -> bool:
        try:
            r = httpx.get(self.s.base_url.rstrip("/") + "/api/tags", timeout=2.0)
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False


class OpenAICompatible:
    """OpenAI-совместимый Chat Completions API с ключом из конфига/.env."""

    def __init__(self, settings: LLMSettings) -> None:
        self.s = settings

    def chat(self, prompt: str, model: str | None = None, timeout: float | None = None) -> str:
        url = self.s.base_url.rstrip("/") + (self.s.api_path or "/chat/completions")
        headers = {"Authorization": f"Bearer {self.s.api_key}"}
        payload: dict[str, Any] = {
            "model": model or self.s.model_main,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.s.temperature,
            "stream": False,
        }
        # Доп. поля API из конфига (llm.extra_body) — например, отключение
        # «размышлений» у reasoning-моделей Zhipu/Z.ai:
        #   extra_body: {"thinking": {"type": "disabled"}}
        payload.update(self.s.extra_body or {})
        r = httpx.post(url, json=payload, headers=headers, timeout=timeout or self.s.timeout_sec)
        r.raise_for_status()
        data = r.json()
        message = data["choices"][0].get("message") or {}
        content = message.get("content") or ""
        if not str(content).strip():
            # reasoning-модели могут вернуть пустой content: пробуем поле рассуждений,
            # ответ модели обычно повторяется в его конце.
            content = message.get("reasoning_content") or ""
        return str(content)

    def ping(self) -> bool:
        if not self.s.api_key:
            return False
        try:
            r = httpx.get(
                self.s.base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {self.s.api_key}"},
                timeout=3.0,
            )
            return r.status_code < 500
        except Exception:  # noqa: BLE001
            return False


class NoneClient:
    """llm.provider: none — работаем без LLM (правила + экстрактивные ответы)."""

    def chat(self, prompt: str, model: str | None = None, timeout: float | None = None) -> str:  # noqa: ARG002
        raise RuntimeError("LLM отключён (llm.provider: none)")

    def ping(self) -> bool:
        return False


def get_llm() -> LLMClient:
    s = load_settings().llm
    if s.provider == "openai_compatible":
        return OpenAICompatible(s)
    if s.provider == "ollama":
        return OllamaClient(s)
    return NoneClient()


def llm_healthy() -> bool:
    provider = load_settings().llm.provider
    if provider == "none":
        return True  # LLM не требуется — деградации нет
    return get_llm().ping()

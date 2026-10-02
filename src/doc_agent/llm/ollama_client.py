"""LLM-клиенты.

- OllamaClient        — локальный Ollama (офлайн-режим ТЗ).
- OpenAICompatible    — ЛЮБАЯ внешняя модель по API с ключом
                        (OpenAI / OpenRouter / Z.ai / LM Studio и т.п.).
Выбор провайдера — только через config/config.yaml: llm.provider.
"""
from __future__ import annotations

import time
from typing import Any, Protocol

import httpx

from doc_agent.config import LLMSettings, load_settings
from doc_agent.logging import get_logger

log = get_logger("llm.client")


def _retry_after_sec(header_value: str | None) -> float | None:
    """Retry-After (секунды) из ответа провайдера; None — нет/не число."""
    if not header_value:
        return None
    try:
        return max(float(header_value), 0.0)
    except ValueError:
        return None


def _api_error(status_code: int, url: str, body: str) -> RuntimeError:
    """v2.8: ошибка API с ТЕЛОМ ответа — без него «400 Bad Request»
    недиагностируемо (реальная причина — «model not found» и т.п.
    — только в JSON-теле ошибки)."""
    return RuntimeError(f"API {status_code} для {url}: {body or '(пустое тело)'}")


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
        # v2.8: ретраи при rate-limit (429)/5xx с учётом Retry-After:
        # бесплатный tier glm-4.5-flash малыми RPM — очередь ингеста без
        # backoff валит классификатор/репортер потоком 429-х.
        attempts = max(self.s.rate_limit_retries, 0) + 1
        last_err: RuntimeError | None = None
        last_wait = 0.0
        for attempt in range(attempts):
            if attempt and last_wait > 0:
                time.sleep(min(last_wait, 30.0))
            r = httpx.post(url, json=payload, headers=headers,
                           timeout=timeout or self.s.timeout_sec)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                err = _api_error(r.status_code, url, (r.text or "").strip()[:300])
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = err
                    ra = _retry_after_sec(r.headers.get("retry-after"))
                    last_wait = ra if ra is not None else \
                        self.s.rate_limit_backoff_sec * (2 ** attempt)
                    if attempt < attempts - 1:
                        continue
                    raise err from exc
                raise err from exc
            data = r.json()
            message = data["choices"][0].get("message") or {}
            content = message.get("content") or ""
            if not str(content).strip():
                # reasoning-модели могут вернуть пустой content: пробуем поле рассуждений,
                # ответ модели обычно повторяется в его конце.
                content = message.get("reasoning_content") or ""
            return str(content)
        raise last_err or RuntimeError("LLM API: исчерпаны все попытки без ответа")

    def ping(self) -> bool:
        if not self.s.api_key:
            return False
        try:
            r = httpx.get(
                self.s.base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {self.s.api_key}"},
                timeout=3.0,
            )
            # v2.7.1: раньше «healthy» был любой ответ < 500 — отказ
            # авторизации (401/403, например неверный ключ или блокировка
            # региона) выглядел как «ok» и маскировал массовые 403 в ingest.
            # Теперь: 2xx — жив; 404 — провайдер не отдаёт /models, но
            # endpoint доступен (считаем живым); 401/403/5xx — нездоров.
            return r.status_code < 300 or r.status_code == 404
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

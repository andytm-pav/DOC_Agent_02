"""A2A-сервер: Agent Card + JSON-RPC 2.0 (tasks/send) — разделы 6.7/8.5 ТЗ.

Протокол реализован напрямую по JSON-RPC контракту ТЗ (a2a-sdk 0.2.* указан
в ТЗ как протокол; здесь — совместимая реализация без внешней зависимости).
"""
from __future__ import annotations

import json
from typing import Any

from doc_agent.config import load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.logging import get_logger
from doc_agent.services import query as query_service

log = get_logger("services.a2a")


def agent_card(base_url: str) -> dict:
    s = load_settings()
    return {
        "name": s.a2a.agent_name,
        "description": "Локальный ИИ-агент «Документовед»: картотека документов, поиск с grounding, воспроизведение.",
        "url": base_url,
        "version": "2.0.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {"id": "document_query", "name": "Поиск по картотеке",
             "description": "Отвечает на вопросы по загруженным документам, только подтверждённые факты."},
            {"id": "document_upload", "name": "Приём документов",
             "description": "Извлечение, классификация и индексация PDF/DOCX/XLSX/OCR и др."},
        ],
    }


def handle_rpc(payload: dict[str, Any]) -> dict:
    """Обрабатывает JSON-RPC 2.0; поддерживает tasks/send (и tasks/get — no-op)."""
    rpc_id = payload.get("id")
    method = str(payload.get("method", ""))

    def _error(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}

    if payload.get("jsonrpc") != "2.0":
        return _error(-32600, "Некорректный Request: jsonrpc должен быть '2.0'")

    if method == "tasks/send":
        params = payload.get("params") or {}
        message = params.get("message") or {}
        parts = message.get("parts") or []
        text = " ".join(str(p.get("text", "")) for p in parts if isinstance(p, dict) and p.get("type") == "text").strip()
        if not text:
            return _error(-32602, "Пустой текст в message.parts")
        try:
            result = query_service.run_query(text)
        except Exception as exc:  # noqa: BLE001
            log.error("a2a_query_failed", error=str(exc))
            return _error(-32000, "Внутренняя ошибка обработки запроса")
        log_audit("a2a", "a2a_tasks_send", {"q": text[:200]})
        artifacts = [{
            "parts": [
                {"type": "text", "text": result["answer"]},
                {"type": "data", "data": {
                    "files": result["files"],
                    "confidence": result["confidence"],
                    "grounded": result["grounded"],
                    "partial": result.get("partial", False),
                }},
            ]
        }]
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"status": "completed", "artifacts": artifacts}}

    if method == "tasks/get":
        return _error(-32601, "tasks/get не поддерживается в v2.0")

    return _error(-32601, f"Метод не найден: {method}")


def dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)

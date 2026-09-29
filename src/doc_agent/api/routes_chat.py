"""Чат: персистентная история и архив памяти (любой авторизованный).

GET  /chat/history        — последние сообщения (переживают обновление страницы)
GET  /chat/archives       — сжатые памятки свёрнутых контекстов
POST /chat/clear-history  — удалить историю чата (архив памяти не трогает)
POST /chat/clear-context  — свернуть актуальный контекст в памятку (в архив)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from doc_agent.auth import get_current_user
from doc_agent.db.models import User
from doc_agent.services import chat as chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/history")
def get_history(limit: int = Query(0, ge=0),
                user: User = Depends(get_current_user)) -> dict:
    return chat_service.history(user.username, limit or None)


@router.get("/archives")
def get_archives(user: User = Depends(get_current_user)) -> dict:
    return {"items": chat_service.archives(user.username)}


@router.post("/clear-history")
def post_clear_history(user: User = Depends(get_current_user)) -> dict:
    deleted = chat_service.clear_history(user.username)
    return {"deleted": deleted, "message": "История чата очищена"}


@router.post("/clear-context")
def post_clear_context(user: User = Depends(get_current_user)) -> dict:
    return chat_service.clear_context(user.username)

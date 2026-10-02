"""Обратная связь (v3.0.0): пользовательский отзыв + админ-CRUD базы ответов.

POST /feedback                — 👍/👎 (+исправленный ответ) от пользователя
                                (право feedback_submit);
GET  /feedback/admin/list     — база проверенных ответов (feedback_manage);
PUT  /feedback/admin/{id}     — правка записи (вопрос/ответ/статус/вес/оценка);
DELETE /feedback/admin/{id}   — удаление записи;
POST /feedback/admin/reembed  — пересборка векторов вопросов
                                (после смены эмбеддинг-модели).

Админ-права: permission feedback_manage ИЛИ admin (require_admin остаётся
для остальных панелей). Эндпоинты размещены отдельным роутером, чтобы
не раздувать routes_admin (минимальные правки).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from doc_agent.auth import require_perm
from doc_agent.db.models import User
from doc_agent.db.session import get_db
from doc_agent.services import feedback

router = APIRouter(tags=["feedback"])


class FeedbackIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    answer: str = Field(..., min_length=1, max_length=20000)
    rating: str = Field("up", pattern="^(up|down)$")
    corrected_answer: str | None = Field(None, max_length=20000)
    file_ids: list[int] = Field(default_factory=list)


@router.post("/feedback")
def post_feedback(body: FeedbackIn,
                  user: User = Depends(require_perm("feedback_submit"))) -> dict:
    try:
        out = feedback.add_or_update(
            user.username or "user", body.question, body.answer, body.rating,
            body.corrected_answer, body.file_ids,
        )
    except RuntimeError as exc:  # feedback.enabled=false
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **out, "message": "Отзыв сохранён — агент учтёт его на похожих вопросах"}


@router.get("/feedback/admin/list")
def admin_list(status: str | None = Query(None),
               limit: int = Query(200, ge=1, le=1000),
               db: Session = Depends(get_db),
               user: User = Depends(require_perm("feedback_manage"))) -> dict:
    return {"items": feedback.list_entries(limit=limit, status=status, db=db),
            "stats": feedback.stats()}


class FeedbackUpdate(BaseModel):
    question: str | None = None
    answer: str | None = None
    corrected_answer: str | None = None
    rating: str | None = Field(None, pattern="^(up|down)$")
    status: str | None = Field(None, pattern="^(active|disabled)$")
    weight: float | None = Field(None, ge=0, le=10)
    file_ids: list[int] | None = None


@router.put("/feedback/admin/{entry_id}")
def admin_update(entry_id: int, body: FeedbackUpdate,
                 user: User = Depends(require_perm("feedback_manage"))) -> dict:
    try:
        return feedback.update_entry(entry_id, body.model_dump(exclude_none=True),
                                     actor=user.username or "admin")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/feedback/admin/{entry_id}")
def admin_delete(entry_id: int,
                 user: User = Depends(require_perm("feedback_manage"))) -> dict:
    try:
        feedback.delete_entry(entry_id, actor=user.username or "admin")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "deleted": entry_id}


@router.post("/feedback/admin/reembed")
def admin_reembed(user: User = Depends(require_perm("feedback_manage"))) -> dict:
    count = feedback.reembed_all(actor=user.username or "admin")
    return {"ok": True, "reembedded": count,
            "message": "Векторы вопросов пересобраны текущей моделью эмбеддингов"}

"""Запросы (6.4): POST /query, POST /query/report.

Чат-эндпоинт /query дополнительно: перехватывает запросы вида «вспомни …»
(подъём архива памяти), передаёт репортеру актуальный контекст беседы и
сохраняет сообщения в персистентную историю (services.chat).
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from doc_agent.auth import get_current_user
from doc_agent.config import load_settings
from doc_agent.db.models import User
from doc_agent.db.session import get_db
from doc_agent.services import card_index
from doc_agent.services import chat as chat_service
from doc_agent.services.query import run_query

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    q: str
    limit: int = Field(20, ge=1, le=100)


@router.post("")
def query(body: QueryRequest, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)) -> dict:
    settings = load_settings()
    # 0. «вспомни …» — подъём сжатого контекста из архива памяти
    recall = chat_service.maybe_recall(user.username, body.q)
    if recall is not None:
        chat_service.add_message(user.username, "user", body.q)
        chat_service.add_message(user.username, "agent", recall["answer"], {
            "recall": True, "archives": recall.get("archives", []),
        })
        return recall
    # 1. актуальный контекст беседы (заархивированное — уже не здесь)
    context = chat_service.context_block(user.username, settings.chat.context_max_messages)
    chat_service.add_message(user.username, "user", body.q)
    try:
        # actor (v3.0.0) — права файловых операций по группам users.yaml
        result = run_query(body.q, limit=body.limit, db=db, context=context,
                           actor=user.username or "user")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ошибка обработки запроса: {exc}") from exc
    chat_service.add_message(user.username, "agent", result["answer"], {
        "grounded": result["grounded"], "confidence": result["confidence"],
        "partial": result["partial"], "files": result["files"],
        "intent": result.get("intent"),
        "known_answer_used": result.get("known_answer_used", False),
    })
    return result


class ReportRequest(BaseModel):
    q: str
    format: str = Field("xlsx", pattern="^(xlsx|md|json)$")


@router.post("/report")
def query_report(body: ReportRequest, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict:
    """Отчёт по запросу: фильтры из вопроса -> выборка картотеки -> файл."""
    result = run_query(body.q, limit=20, db=db)
    filters = result.get("filters", {})
    data = card_index.query_card(
        db,
        doc_type=filters.get("doc_type"),
        contract_no=filters.get("contract_no"),
        city=filters.get("city"),
        limit=10000,
    )
    stamp = int(time.time() * 1000)
    if body.format == "json":
        path = Path(tempfile.gettempdir()) / f"report_{stamp}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return {"download_url": f"/query/report/download/{path.name}"}
    if body.format == "md":
        path = Path(tempfile.gettempdir()) / f"report_{stamp}.md"
        lines = [f"# Отчёт по запросу: {body.q}", "", f"Всего: {data['total']}", ""]
        for item in data["items"]:
            lines.append(f"- [{item['id']}] {item['original_name']} — {item['doc_type']} (договор {item['contract_no']})")
        path.write_text("\n".join(lines), encoding="utf-8")
        return {"download_url": f"/query/report/download/{path.name}"}
    content = card_index.export_xlsx(data["items"])
    path = Path(tempfile.gettempdir()) / f"report_{stamp}.xlsx"
    path.write_bytes(content)
    return {"download_url": f"/query/report/download/{path.name}"}


@router.get("/report/download/{name}")
def download_report(name: str, user: User = Depends(get_current_user)) -> FileResponse:
    path = Path(tempfile.gettempdir()) / Path(name).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    return FileResponse(str(path), filename=path.name)

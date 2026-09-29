"""Картотека (6.3): GET /card с фильтрами + GET /card/export.xlsx.

Поддерживается ?token=<jwt> для скачивания из браузера (без заголовка Authorization).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from doc_agent.auth import get_current_user
from doc_agent.db.models import User
from doc_agent.db.session import get_db
from doc_agent.services import card_index

router = APIRouter(prefix="/card", tags=["card"])


@router.get("")
def card(
    city: str | None = Query(None),
    customer: str | None = Query(None),
    contract_no: str | None = Query(None),
    doc_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return card_index.query_card(
        db, city=city, customer=customer, contract_no=contract_no, doc_type=doc_type,
        date_from=date_from, date_to=date_to, limit=limit, offset=offset,
    )


@router.get("/export.xlsx")
def export_xlsx(
    city: str | None = Query(None),
    customer: str | None = Query(None),
    contract_no: str | None = Query(None),
    doc_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(10000, ge=1, le=100000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    data = card_index.query_card(
        db, city=city, customer=customer, contract_no=contract_no, doc_type=doc_type,
        date_from=date_from, date_to=date_to, limit=limit, offset=offset,
    )
    content = card_index.export_xlsx(data["items"])
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=card_index.xlsx"},
    )

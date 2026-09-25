"""Query routes."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from doc_agent.auth import get_current_user
from doc_agent.services.query import query_documents
from doc_agent.services.card_index import get_card_index, export_card_index_xlsx

router = APIRouter()


class QueryRequest(BaseModel):
    q: str
    limit: int = 20


class ReportRequest(BaseModel):
    q: str
    format: str = "xlsx"


@router.post("")
async def query(
    req: QueryRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Query documents and get an answer."""
    result = await query_documents(req.q, req.limit)
    return result


@router.post("/report")
async def report(
    req: ReportRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Generate a report."""
    if req.format == "xlsx":
        path = export_card_index_xlsx()
        return {"download_url": f"/card/export.xlsx"}
    return {"download_url": None}


@router.get("/card")
async def card_index(
    city: str | None = None,
    customer: str | None = None,
    contract_no: str | None = None,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user),
) -> dict:
    """Get the card index."""
    return get_card_index(
        city=city,
        customer=customer,
        contract_no=contract_no,
        doc_type=doc_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/card/export.xlsx")
async def export_xlsx(
    city: str | None = None,
    customer: str | None = None,
    contract_no: str | None = None,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(get_current_user),
) -> FileResponse:
    """Export card index to XLSX."""
    path = export_card_index_xlsx(
        city=city,
        customer=customer,
        contract_no=contract_no,
        doc_type=doc_type,
        date_from=date_from,
        date_to=date_to,
    )
    return FileResponse(path, filename="card_index.xlsx")

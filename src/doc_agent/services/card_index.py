"""Card index service for document catalog."""

from datetime import datetime
from typing import Any

from doc_agent.db.session import get_session
from doc_agent.db.models import File


def get_card_index(
    city: str | None = None,
    customer: str | None = None,
    contract_no: str | None = None,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Get the card index with filters."""
    with get_session() as session:
        query = session.query(File)

        if city:
            query = query.filter(File.city == city)
        if customer:
            query = query.filter(File.customer.ilike(f"%{customer}%"))
        if contract_no:
            query = query.filter(File.contract_no == contract_no)
        if doc_type:
            query = query.filter(File.doc_type == doc_type)
        if date_from:
            query = query.filter(File.doc_date >= date_from)
        if date_to:
            query = query.filter(File.doc_date <= date_to)

        total = query.count()
        items = query.offset(offset).limit(limit).all()

        return {
            "total": total,
            "items": [
                {
                    "id": f.id,
                    "original_name": f.original_name,
                    "format": f.format,
                    "size_bytes": f.size_bytes,
                    "city": f.city,
                    "customer": f.customer,
                    "contract_no": f.contract_no,
                    "contract_date": f.contract_date,
                    "doc_type": f.doc_type,
                    "doc_number": f.doc_number,
                    "doc_date": f.doc_date,
                    "amount": f.amount,
                    "status": f.status,
                    "ocr_confidence": f.ocr_confidence,
                    "description": f.description,
                    "source": f.source,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in items
            ],
        }


def export_card_index_xlsx(
    city: str | None = None,
    customer: str | None = None,
    contract_no: str | None = None,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Export card index to XLSX with 15 columns and auto-filter."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    data = get_card_index(
        city=city,
        customer=customer,
        contract_no=contract_no,
        doc_type=doc_type,
        date_from=date_from,
        date_to=date_to,
        limit=10000,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Картотека"

    # 15 columns as per specification
    headers = [
        "ID", "Имя файла", "Формат", "Размер (байт)", "Город",
        "Контрагент", "№ договора", "Дата договора", "Тип документа",
        "№ документа", "Дата документа", "Сумма", "Статус",
        "OCR точность", "Описание",
    ]

    for col, header in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=header)

    for row_idx, item in enumerate(data["items"], 2):
        ws.cell(row=row_idx, column=1, value=item["id"])
        ws.cell(row=row_idx, column=2, value=item["original_name"])
        ws.cell(row=row_idx, column=3, value=item["format"])
        ws.cell(row=row_idx, column=4, value=item["size_bytes"])
        ws.cell(row=row_idx, column=5, value=item["city"] or "")
        ws.cell(row=row_idx, column=6, value=item["customer"] or "")
        ws.cell(row=row_idx, column=7, value=item["contract_no"] or "")
        ws.cell(row=row_idx, column=8, value=item["contract_date"] or "")
        ws.cell(row=row_idx, column=9, value=item["doc_type"] or "")
        ws.cell(row=row_idx, column=10, value=item["doc_number"] or "")
        ws.cell(row=row_idx, column=11, value=item["doc_date"] or "")
        ws.cell(row=row_idx, column=12, value=item["amount"])
        ws.cell(row=row_idx, column=13, value=item["status"])
        ws.cell(row=row_idx, column=14, value=item["ocr_confidence"])
        ws.cell(row=row_idx, column=15, value=item["description"] or "")

    # Auto-filter
    last_col = get_column_letter(len(headers))
    last_row = len(data["items"]) + 1
    ws.auto_filter.ref = f"A1:{last_col}{last_row}"

    # Save
    output_path = "data/card_index.xlsx"
    wb.save(output_path)
    return output_path

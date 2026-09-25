"""File management routes."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from doc_agent.auth import get_current_user
from doc_agent.config import get_settings
from doc_agent.db.session import get_session
from doc_agent.db.models import File as FileModel, Chunk
from doc_agent.services.ingest import ingest_file
from doc_agent.services.reproduce import reproduce_document

router = APIRouter()


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    source: str = "user",
    user: dict = Depends(get_current_user),
) -> dict:
    """Upload a file for processing."""
    settings = get_settings()

    # Check file size
    content = await file.read()
    if len(content) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_file_mb} MB",
        )

    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "").suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = ingest_file(tmp_path, file.filename or "unknown", source)
        return result
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/{file_id}")
async def get_file(
    file_id: int,
    user: dict = Depends(get_current_user),
) -> dict:
    """Get file metadata."""
    with get_session() as session:
        file = session.query(FileModel).filter(FileModel.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        chunks_count = session.query(Chunk).filter(Chunk.file_id == file_id).count()

        return {
            "file": {
                "id": file.id,
                "sha256": file.sha256,
                "original_name": file.original_name,
                "format": file.format,
                "size_bytes": file.size_bytes,
                "city": file.city,
                "customer": file.customer,
                "contract_no": file.contract_no,
                "contract_date": file.contract_date,
                "doc_type": file.doc_type,
                "doc_number": file.doc_number,
                "doc_date": file.doc_date,
                "amount": file.amount,
                "status": file.status,
                "ocr_confidence": file.ocr_confidence,
                "description": file.description,
                "source": file.source,
                "created_at": file.created_at.isoformat() if file.created_at else None,
            },
            "links": [],
            "chunks_count": chunks_count,
        }


@router.get("/{file_id}/tree")
async def get_file_tree(
    file_id: int,
    user: dict = Depends(get_current_user),
) -> dict:
    """Get the document tree."""
    import json

    with get_session() as session:
        file = session.query(FileModel).filter(FileModel.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        tree_path = Path(file.stored_path).parent / "tree.json"
        if not tree_path.exists():
            raise HTTPException(status_code=404, detail="Tree not found")

        with open(tree_path, encoding="utf-8") as f:
            return json.load(f)


@router.post("/{file_id}/reproduce")
async def reproduce_file(
    file_id: int,
    target_format: str = "docx",
    user: dict = Depends(get_current_user),
) -> dict:
    """Reproduce a document in a different format."""
    try:
        output_path = await reproduce_document(file_id, target_format)
        return {"download_url": f"/files/{file_id}/download/{Path(output_path).name}"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{file_id}/download/{filename}")
async def download_file(
    file_id: int,
    filename: str,
    user: dict = Depends(get_current_user),
) -> FileResponse:
    """Download a reproduced file."""
    with get_session() as session:
        file = session.query(FileModel).filter(FileModel.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        file_path = Path(file.stored_path).parent / "reproduced" / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(str(file_path))

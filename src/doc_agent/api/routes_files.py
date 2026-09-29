"""Файлы + OCR (6.2, 6.5): upload, get, tree, reproduce, download, suspects, correct."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi import File as UploadField
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_agent.auth import get_current_user
from doc_agent.config import load_settings
from doc_agent.db.models import Chunk, File, FileLink, Job, User
from doc_agent.db.session import get_db
from doc_agent.services import ingest, ocr_fix, reproduce, sorting
from doc_agent.services.ingest import human_message

router = APIRouter(tags=["files"])


@router.post("/files/upload")
def upload_file(
    file: UploadFile = UploadField(...),
    source: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    settings = load_settings()
    tmp_dir = settings.app.sub_dir("tmp")
    suffix = Path(file.filename or "upload.bin").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=tmp_dir) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        result = ingest.enqueue_file(tmp_path, file.filename or "upload.bin", source=source or "user")
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return result


@router.get("/files/{file_id}")
def get_file(file_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> dict:
    f = db.get(File, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    links = db.execute(
        select(FileLink).where((FileLink.parent_id == file_id) | (FileLink.child_id == file_id))
    ).scalars().all()
    chunks_count = len(db.execute(select(Chunk.id).where(Chunk.file_id == file_id)).all())
    file_payload = {c.name: getattr(f, c.name) for c in File.__table__.columns}
    return {
        "file": file_payload,
        "links": [
            {"parent_id": lnk.parent_id, "child_id": lnk.child_id, "link_type": lnk.link_type}
            for lnk in links
        ],
        "chunks_count": chunks_count,
        "message": human_message(f) if f.status == "done" else None,
    }


@router.get("/files/{file_id}/tree")
def get_tree(file_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> dict:
    f = db.get(File, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    tree_path = Path(f.stored_path).parent / "tree.json"
    if not tree_path.exists():
        raise HTTPException(status_code=404, detail="Дерево не построено (файл в обработке или description_only)")
    import json

    return json.loads(tree_path.read_text(encoding="utf-8"))


class ReproduceRequest(BaseModel):
    target_format: str


class ScanFolderRequest(BaseModel):
    """Импорт свалки файлов из папки (папку указывает пользователь)."""

    path: str
    recursive: bool | None = None  # None = взять из конфига ingest.recursive


@router.post("/files/scan-folder")
def scan_folder_endpoint(body: ScanFolderRequest, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict:
    try:
        return ingest.scan_folder(body.path, body.recursive, source="folder")
    except NotADirectoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"Нет доступа к папке: {exc}") from exc


class SortFolderRequest(BaseModel):
    """Разгребание свалки: разложить файлы по тематическим папкам."""

    path: str
    output_path: str | None = None  # None = рядом со свалкой (sorting.default_output_suffix)
    recursive: bool | None = None   # None = взять из конфига sorting.recursive


@router.post("/files/sort-folder")
def sort_folder_start_endpoint(body: SortFolderRequest,
                               user: User = Depends(get_current_user)) -> dict:
    """Запускает разбор свалки в фоне, возвращает job_id для опроса статуса."""
    try:
        job_id = sorting.sort_folder_start(
            body.path, body.output_path, body.recursive, actor=user.username or "user")
    except NotADirectoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"Нет доступа к папке: {exc}") from exc
    except RuntimeError as exc:  # функция отключена в конфиге
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "state": "running"}


@router.get("/files/sort-folder/{job_id}")
def sort_folder_status_endpoint(job_id: str,
                                user: User = Depends(get_current_user)) -> dict:
    job = sorting.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return job


@router.post("/files/{file_id}/reproduce")
def reproduce_file(file_id: int, body: ReproduceRequest,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    try:
        return reproduce.start_reproduce(file_id, body.target_format)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/files/{file_id}/download/{job_id}")
def download(file_id: int, job_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> FileResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if job.status != "done":
        raise HTTPException(status_code=409, detail=f"Файл готовится (job status: {job.status})")
    fmt = job.kind.split(":", 1)[-1]
    path = reproduce.artifact_path(file_id, job_id, fmt)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Артефакт не найден")
    return FileResponse(str(path), filename=path.name)


# --- OCR-исправления (6.5) ---

@router.get("/ocr/{file_id}/suspects")
def ocr_suspects(file_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict:
    try:
        return ocr_fix.suspects(db, file_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class CorrectRequest(BaseModel):
    chunk_id: int
    corrected: str


@router.post("/ocr/{file_id}/correct")
def ocr_correct(file_id: int, body: CorrectRequest, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    try:
        return ocr_fix.correct(db, file_id, body.chunk_id, body.corrected, user.username or "user")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

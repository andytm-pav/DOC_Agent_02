"""File ingestion service."""

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

import structlog

from doc_agent.config import get_settings
from doc_agent.db.session import get_session
from doc_agent.db.models import File, Job

logger = structlog.get_logger()


def compute_sha256(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def ingest_file(
    source_path: str,
    original_name: str,
    source: str = "user",
) -> dict:
    """Ingest a file into the system."""
    settings = get_settings()
    storage_dir = Path(settings.data_dir) / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    # Compute hash
    sha256 = compute_sha256(source_path)

    # Determine format
    ext = Path(original_name).suffix.lstrip(".").lower()
    if not ext:
        raise ValueError("Cannot determine file format")

    with get_session() as session:
        # Check for duplicate
        existing = session.query(File).filter(File.sha256 == sha256).first()
        if existing:
            logger.info("Duplicate file detected", sha256=sha256, existing_id=existing.id)
            return {"file_id": existing.id, "status": "duplicate", "message": "Файл уже существует"}

        # Create storage directory
        file_storage = storage_dir / sha256
        file_storage.mkdir(parents=True, exist_ok=True)

        # Copy file
        stored_path = str(file_storage / f"original.{ext}")
        shutil.copy2(source_path, stored_path)

        # Create file record
        file_record = File(
            sha256=sha256,
            original_name=original_name,
            stored_path=stored_path,
            format=ext,
            size_bytes=Path(source_path).stat().st_size,
            mtime=datetime.now(timezone.utc).isoformat(),
            status="pending",
            source=source,
        )
        session.add(file_record)
        session.flush()

        # Create ingest job
        job = Job(
            file_id=file_record.id,
            kind="ingest",
            priority=1,
            status="queued",
        )
        session.add(job)
        session.commit()

        logger.info("File ingested", file_id=file_record.id, sha256=sha256, format=ext)
        return {
            "file_id": file_record.id,
            "status": "queued",
            "message": "Файл принят",
        }

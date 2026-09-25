"""OCR fix service."""

import structlog

from doc_agent.db.session import get_session
from doc_agent.db.models import Chunk, File, OcrCorrection, Job

logger = structlog.get_logger()


def get_suspects(file_id: int) -> list[dict]:
    """Get chunks with low OCR confidence."""
    with get_session() as session:
        file = session.query(File).filter(File.id == file_id).first()
        if not file or file.ocr_confidence is None:
            return []

        if file.ocr_confidence >= 0.80:
            return []

        chunks = session.query(Chunk).filter(Chunk.file_id == file_id).all()
        return [
            {
                "chunk_id": c.id,
                "text": c.text,
                "confidence": file.ocr_confidence,
            }
            for c in chunks
        ]


def apply_correction(
    file_id: int,
    chunk_id: int,
    corrected: str,
    user: str,
) -> dict:
    """Apply an OCR correction."""
    with get_session() as session:
        chunk = session.query(Chunk).filter(Chunk.id == chunk_id).first()
        if not chunk:
            raise ValueError(f"Chunk not found: {chunk_id}")

        original = chunk.text

        # Calculate edit distance ratio
        edit_dist = _edit_distance(original, corrected)
        ratio = edit_dist / max(len(original), 1)

        if ratio > 0.5:
            return {
                "status": "reject",
                "message": "Загрузите скан ≥300 dpi, текущий не поддаётся распознаванию.",
            }

        # Save correction
        correction = OcrCorrection(
            file_id=file_id,
            original=original,
            corrected=corrected,
            user=user,
        )
        session.add(correction)

        # Update chunk
        chunk.text = corrected
        session.flush()

        # Create reindex job
        job = Job(
            file_id=file_id,
            kind="reindex",
            priority=2,
            status="queued",
        )
        session.add(job)
        session.commit()

        return {
            "status": "ok",
            "reindex_job": job.id,
        }


def _edit_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance."""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]

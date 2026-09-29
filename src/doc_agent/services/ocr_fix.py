"""OCR-исправления (8.3): suspects -> corrected -> словарь -> переиндексация."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import Chunk, File, OcrCorrection
from doc_agent.logging import get_logger
from doc_agent.services.jobs import enqueue_reindex

log = get_logger("services.ocr_fix")


def edit_distance(a: str, b: str) -> int:
    """Расстояние Левенштейна (для коротких строк допустим O(n*m))."""
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def suspects(db: Session, file_id: int) -> dict:
    """Фрагменты с низкой OCR-уверенностью (порог из config)."""
    s = load_settings().ocr
    f = db.get(File, file_id)
    if f is None:
        raise LookupError("Файл не найден")
    threshold = s.min_confidence
    items: list[dict] = []
    if f.ocr_confidence is not None and f.ocr_confidence < threshold:
        chunks = db.execute(
            select(Chunk).where(Chunk.file_id == file_id).order_by(Chunk.chunk_index).limit(50)
        ).scalars().all()
        items = [
            {"chunk_id": c.id, "text": c.text, "confidence": f.ocr_confidence}
            for c in chunks
        ]
    return {"suspects": items}


def correct(db: Session, file_id: int, chunk_id: int, corrected: str, username: str) -> dict:
    chunk = db.get(Chunk, chunk_id)
    if chunk is None or chunk.file_id != file_id:
        raise LookupError("Фрагмент не найден")
    original = chunk.text

    # 8.3 шаг 3-4: если >50% отличий — файл не поддаётся, просим скан >=300 dpi
    if original:
        ratio = edit_distance(original, corrected) / max(len(original), 1)
        if ratio > 0.5:
            return {
                "status": "rejected",
                "message": "Загрузите скан ≥300 dpi, текущий не поддаётся распознаванию.",
                "ratio": round(ratio, 2),
            }
    else:
        return {"status": "rejected", "message": "Пустой исходный фрагмент — исправление невозможно.", "ratio": 1.0}

    # 8.3 шаг 5a-5c
    db.add(OcrCorrection(file_id=file_id, original=original, corrected=corrected, user=username))
    chunk.text = corrected
    f = db.get(File, file_id)
    if f is not None:
        f.ocr_confidence = max(f.ocr_confidence or 0.0, 0.95)
    db.commit()

    words_file = load_settings().app.data_path / "user_words.txt"
    with open(words_file, "a", encoding="utf-8") as wf:
        wf.write(corrected.strip() + "\n")

    reindex_job = enqueue_reindex(file_id)
    log_audit(username, "ocr_corrected", {"file_id": file_id, "chunk_id": chunk_id})

    # 8.3 шаг 6: уточняющие вопросы
    questions = [
        f"Верно ли я понял: «{corrected.strip()}»?",
        "Добавить в словарь для будущих документов?",
    ]
    return {"status": "ok", "reindex_job": reindex_job, "questions": questions}

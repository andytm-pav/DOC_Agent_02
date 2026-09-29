"""Глубокое чтение файла(ов) — ПОЛНЫЙ текст в промпт LLM.

Векторный поиск выдаёт только 5 фрагментов по ~1200 символов — для вопросов
вида «что в файле Х?» или «прочитай договор …» этого мало. Здесь ПОЛНЫЙ
текст файла (чанки из БД по порядку, до qa.deep_read_max_chars) попадает
в промпт LLM целиком — ответ развёрнутый, на естественном языке,
с цитатами [file_id:N].

Как выбираются файлы (v2.6):
  - file_ids из плана LLM-планировщика (services/planner.py) — приоритет;
  - термы из плана (terms) -> сопоставление с картотекой;
  - без плана — термы из вопроса (офлайн-fallback).

Вызовы: явная просьба (deep_read_cues, офлайн-fallback) и автодочтение
после «НЕТ ДАННЫХ» (deep_read_on_no_data); с v2.6 — прямое указание
планировщика (action=read_file).

Без LLM (provider: none) — None: работает экстрактивный путь репортера.
Промпт — config/prompts/deep_read.txt (инлайн-промпты запрещены).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import Chunk, File
from doc_agent.llm.ollama_client import get_llm
from doc_agent.llm.prompts import get_prompt
from doc_agent.logging import get_logger
from doc_agent.services.intents import (
    _load_files,
    _payload,
    name_terms,
    ranked_files,
)

if TYPE_CHECKING:
    from doc_agent.config import QaSettings

log = get_logger("services.deep_read")


def _file_text(db: Session, file_id: int, max_chars: int) -> str:
    """Полный текст файла из чанков (по порядку), обрезанный до max_chars."""
    parts: list[str] = []
    total = 0
    rows = db.execute(
        select(Chunk.text).where(Chunk.file_id == file_id).order_by(Chunk.chunk_index)
    ).yield_per(200)
    for (text,) in rows:
        t = text or ""
        if total + len(t) <= max_chars:
            parts.append(t)
            total += len(t)
        else:
            rest = max_chars - total
            if rest > 0:
                parts.append(t[:rest])
                total += rest
            break
        if total >= max_chars:
            break
    return "\n".join(parts)


def _documents_block(db: Session, files: list, s: QaSettings) -> str:
    """Блок «Документы» для промпта: заголовок файла + его полный текст."""
    per_file = max(500, s.deep_read_max_chars // max(len(files), 1))
    blocks: list[str] = []
    for f in files:
        text = _file_text(db, f.id, per_file)
        if not text.strip():
            continue
        blocks.append(f"[file_id:{f.id}] {f.original_name}:\n{text}")
    return "\n\n".join(blocks)


def try_deep_read(
    question: str, db: Session, require_cue: bool,
    file_ids: list[int] | None = None, terms: list[str] | None = None,
) -> dict | None:
    """Отвечает по ПОЛНОМУ тексту файлов.

    file_ids/terms — параметры из плана планировщика (v2.6); без плана
    файлы подбираются по терсам вопроса. require_cue=True — только по
    явной просьбе (deep_read_cues, офлайн-fallback); планировщик и
    автодочтение вызывают с require_cue=False. Возвращает ответ в
    формате /query или None — глубокое чтение неприменимо (нет
    совпадений/текста/LLM).
    """
    settings = load_settings()
    if settings.llm.provider == "none":
        return None
    s = settings.qa
    low = (question or "").lower().strip()
    if not low:
        return None
    cue = any(c in low for c in s.deep_read_cues)
    if require_cue and not cue:
        return None

    files: list[File]
    if file_ids:
        # планировщик назвал конкретные файлы — читаем именно их
        by_id = {f.id: f for f in _load_files(db)}
        files = [by_id[i] for i in file_ids if i in by_id][: s.deep_read_max_files]
    else:
        if terms is None:
            terms = name_terms(question, [])
        if not terms:
            return None
        files = ranked_files(terms, _load_files(db))[: s.deep_read_max_files]
    if not files:
        return None

    documents = _documents_block(db, files, s)
    if not documents.strip():
        return None

    try:
        prompt = get_prompt("deep_read", question=question, documents=documents)
        answer = get_llm().chat(prompt, model=settings.llm.model_main).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("deep_read_llm_failed", error=str(exc), files=[f.id for f in files])
        return None
    if not answer:
        return None

    log_audit("query", "query_answered", {
        "q": question[:200], "intent": "deep_read",
        "files": [f.id for f in files],
        "cue": cue,
    })
    log.info("deep_read_done", files=[f.id for f in files], chars=len(documents), cue=cue)
    return {
        "answer": answer,
        "files": [_payload(f) for f in files],
        "confidence": s.deep_read_confidence,
        "grounded": True,
        "partial": False,
        "filters": {},
        "intent": "deep_read",
    }

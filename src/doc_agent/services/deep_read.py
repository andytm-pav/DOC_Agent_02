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

v3.0.3: ответ глубокого чтения проходит ТОТ ЖЕ grounding-фильтр
(groundrails.validate_answer), что и RAG-ответ: корпус проверки — тексты
файлов, ушедшие в промпт. Раньше deep_read был единственным LLM-путём
без анти-галлюцинации: выдуманная «сводка» по целому файлу уходила
пользователю без проверки. Полностью неподтверждённый ответ -> None
(вопрос идёт в обычный RAG-путь), частично — вырезанное + partial=True
и уверенность, пропорциональная доле уцелевшего.

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
from doc_agent.services.groundrails import validate_answer
from doc_agent.services.intents import (
    _load_files,
    _payload,
    name_terms,
    ranked_files,
)

if TYPE_CHECKING:
    from doc_agent.config import QaSettings

log = get_logger("services.deep_read")


def _stitch(full: str, max_chars: int) -> str:
    """v3.0.1: голова+хвост вместо обрезки только по голове.

    Раньше длинный файл резался с начала: у больших договоров терялся
    КОНЕЦ — а там реквизиты, подписи, гарантийные условия, приложения.
    Теперь при нехватке бюджета берётся начало (~65%) + конец (~35%)
    с честной пометкой о пропущенной середине (фабрика промптов
    сохраняет структуру, LLM видит, что текст неполон)."""
    if max_chars <= 0 or len(full) <= max_chars:
        return full
    marker_len = 60
    head = max(0, max_chars * 65 // 100)
    tail = max(0, max_chars - head - marker_len)
    skipped = len(full) - head - tail
    marker = f"\n[…пропущено ~{skipped} символов середины файла; конец документа ниже…]\n"
    return full[:head] + marker + (full[-tail:] if tail > 0 else "")


def _file_text(db: Session, file_id: int, max_chars: int) -> str:
    """Текст файла из чанков (по порядку), уложенный в max_chars.
    v3.0.1: переполнение сворачивается в голову+хвост (_stitch), а не
    в обрезку с начала — большие документы сохраняют концовку."""
    texts: list[str] = []
    rows = db.execute(
        select(Chunk.text).where(Chunk.file_id == file_id).order_by(Chunk.chunk_index)
    ).yield_per(200)
    for (text,) in rows:
        texts.append(text or "")
    return _stitch("\n".join(texts), max_chars)


def _documents_block(db: Session, files: list, s: QaSettings) -> tuple[str, list[str]]:
    """Блок «Документы» для промпта: заголовок файла + его полный текст.

    v3.0.3: возвращает также тексты по файлам — они становятся корпусом
    grounding-валидации ответа (анти-галлюцинация наравне с RAG-путём)."""
    per_file = max(500, s.deep_read_max_chars // max(len(files), 1))
    blocks: list[str] = []
    texts: list[str] = []
    for f in files:
        text = _file_text(db, f.id, per_file)
        if not text.strip():
            continue
        blocks.append(f"[file_id:{f.id}] {f.original_name}:\n{text}")
        texts.append(text)
    return "\n\n".join(blocks), texts


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

    documents, doc_texts = _documents_block(db, files, s)
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

    # v3.0.3: grounding-фильтр (тот же, что у RAG-ответа); корпус — тексты
    # файлов из промпта, поэтому всё, что LLM реально видела, проходит.
    frags = [
        {"file_id": f.id, "file_name": f.original_name,
         "doc_type": f.doc_type or "other", "text": t}
        for f, t in zip(files, doc_texts)
    ]
    validated = validate_answer(answer, frags)
    validated_answer = str(validated.get("answer", "")).strip()
    if not validated_answer or validated_answer == "НЕТ ДАННЫХ":
        # выдумка целиком: механизм «не ответил» — вопрос уйдёт в RAG-путь
        log.warning("deep_read_answer_ungrounded", files=[f.id for f in files])
        return None
    cut = float(validated.get("cut_ratio", 0.0))

    log_audit("query", "query_answered", {
        "q": question[:200], "intent": "deep_read",
        "files": [f.id for f in files],
        "cue": cue,
    })
    log.info("deep_read_done", files=[f.id for f in files], chars=len(documents), cue=cue,
             cut_ratio=round(cut, 3))
    return {
        "answer": validated_answer,
        "files": [_payload(f) for f in files],
        # уверенность пропорциональна доле уцелевших утверждений
        # (cut_ratio=0 -> прежнее значение deep_read_confidence)
        "confidence": round(max(0.0, s.deep_read_confidence) * (1.0 - cut), 2),
        "grounded": bool(validated.get("grounded")),
        "partial": bool(validated.get("partial")),
        "filters": {},
        "intent": "deep_read",
    }

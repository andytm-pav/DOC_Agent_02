"""LLM-планировщик чата (v2.6) — понимание вопроса на естественном языке.

Вместо жёстких привязок к фразам («сколько…», «покажи все…») вопрос сначала
разбирает LLM: он видит картотеку файлов и краткий контекст беседы, понимает,
ЧТО нужно пользователю, и возвращает строгий JSON-план:

    {"action": "count_files|list_files|find_files|read_file|search_content|
                help|direct",
     "doc_type": "ks2|...|null",
     "terms": ["вилоновская", "23"],     # термы для поиска по картотеке
     "file_ids": [12],                   # файлы для read_file (из картотеки)
     "search_query": "...",              # переформулированный запрос для RAG
     "reply": "..."}                     # текст прямого ответа (action=direct)

Дальше план исполняют ДЕТЕРМИНИРОВАННЫЕ механизмы (SQL-картотека, гибридный
поиск, глубокое чтение), а финальную формулировку делает LLM (репортер,
синтез, глубокое чтение).

Отказобезопасность: сбой LLM / не-JSON / неизвестное действие -> None —
вопрос обрабатывается детерминированным fallback'ом (ключевые слова qa.*
из config.yaml, затем обычный RAG). Парсер — utils.json_extract
(переживает <think>, ограждения ```json и текст вокруг JSON).
Промпт — config/prompts/planner.txt (инлайн-промпты запрещены).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.models import File
from doc_agent.llm.ollama_client import get_llm
from doc_agent.llm.prompts import get_prompt
from doc_agent.logging import get_logger
from doc_agent.utils.json_extract import extract_json

log = get_logger("services.planner")


def _validate(raw: str, db: Session) -> dict[str, Any] | None:
    """Разбор и санитизация плана. None — план недействителен."""
    s = load_settings()
    p = s.planner
    data = extract_json(raw)
    if not isinstance(data, dict):
        return None
    action = str(data.get("action", "")).strip()
    if action not in set(p.allowed_actions):
        return None
    if action == "direct" and not p.allow_direct_reply:
        return None

    doc_type: str | None = None
    raw_type = data.get("doc_type")
    if isinstance(raw_type, str) and raw_type.strip():
        candidate = raw_type.strip().lower()
        if candidate in s.qa.doc_type_labels:
            doc_type = candidate

    terms: list[str] = []
    raw_terms = data.get("terms")
    if isinstance(raw_terms, list):
        for t in raw_terms:
            if not isinstance(t, str):
                continue
            t = t.strip().lower()
            # служебные слова и обрывки в поиск по картотеке не попадают
            if len(t) < 2 or t in s.qa.name_stopwords or t in terms:
                continue
            terms.append(t)
            if len(terms) >= p.max_terms:
                break

    file_ids: list[int] = []
    raw_ids = data.get("file_ids")
    if isinstance(raw_ids, list):
        existing = set(db.execute(select(File.id)).scalars().all())
        for v in raw_ids:
            try:
                i = int(v)
            except (TypeError, ValueError):
                continue
            if i in existing and i not in file_ids:
                file_ids.append(i)

    search_query = ""
    raw_query = data.get("search_query")
    if isinstance(raw_query, str) and raw_query.strip():
        search_query = raw_query.strip()[: s.limits.max_query_len]

    reply = ""
    if isinstance(data.get("reply"), str):
        reply = data["reply"].strip()

    return {
        "action": action,
        "doc_type": doc_type,
        "terms": terms,
        "file_ids": file_ids,
        "search_query": search_query,
        "reply": reply,
    }


def build_plan(question: str, db: Session, context: str | None) -> dict[str, Any] | None:
    """Понимает вопрос на естественном языке и возвращает план механизма.

    None — планирование невозможно/не удалось (LLM отключён, выключен в
    конфиге, сбой после retries) — вызывающий уходит в детерминированный
    fallback. Внутри одной обработки вопроса load_settings() читается
    один раз.
    """
    s = load_settings()
    p = s.planner
    if not p.enabled or s.llm.provider == "none":
        return None
    low = (question or "").strip()
    if not low:
        return None

    catalog = ""
    if p.catalog_for_planner:
        from doc_agent.services.intents import catalog_block

        catalog = catalog_block(db)[: p.catalog_max_chars]
    ctx = (context or "").strip()[: p.context_max_chars]
    actions = ", ".join(p.allowed_actions)
    doc_types = ", ".join(f"{code} = {label}" for code, label in s.qa.doc_type_labels.items())

    prompt = get_prompt(
        "planner",
        question=low,
        catalog=catalog or "(картотека пуста)",
        context=ctx or "(пусто)",
        actions=actions,
        doc_types=doc_types,
    )
    model = s.llm.model_main if p.model == "main" else s.llm.model_light
    llm = get_llm()
    for attempt in range(1, max(p.retries, 0) + 2):
        try:
            raw = llm.chat(prompt, model=model, timeout=p.timeout_sec)
            plan = _validate(raw, db)
            if plan is not None:
                log.info(
                    "plan_built",
                    action=plan["action"],
                    terms=plan["terms"],
                    file_ids=plan["file_ids"],
                    doc_type=plan["doc_type"],
                    attempt=attempt,
                )
                return plan
            log.warning("planner_invalid_plan", attempt=attempt)
        except Exception as exc:  # noqa: BLE001
            log.warning("planner_attempt_failed", attempt=attempt, error=str(exc))
    log.info("planner_fallback_keywords")
    return None

"""Чат: персистентная история и память (контекст) беседы.

История сообщений хранится в БД (chat_messages) и переживает обновление
страницы — видна, пока пользователь не нажмёт «Очистить историю».
Контекст — последние активные сообщения (active=1): они передаются
репортеру при ответе на вопрос. «Очистить контекст» сжимает активные
сообщения в памятку (context_archives; LLM-суммаризация по промпту из
config/prompts/context_summary.txt, без LLM — выжимка из вопросов) и
помечает их active=0: архив НЕ занимает контекстное окно актуального
контекста и поднимается по запросу вида «вспомни …» — ключевые слова
берутся из конфига (chat.recall_keywords), ответ по промпту
config/prompts/context_recall.txt (без LLM — выжимка из памяток).

Настройки — только config/config.yaml (секция chat); инлайн-промпты
запрещены.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import ChatMessage, ContextArchive
from doc_agent.db.session import get_session_factory
from doc_agent.llm.ollama_client import get_llm
from doc_agent.llm.prompts import get_prompt
from doc_agent.logging import get_logger
from doc_agent.utils.json_extract import extract_json

log = get_logger("services.chat")

_WORD_RE = re.compile(r"[а-яёa-z0-9][а-яёa-z0-9\-]*")

_ROLE_LABEL = {"user": "Пользователь", "agent": "Агент", "system": "Система"}


# ---------- история ----------

def add_message(
    user: str, role: str, content: str, meta: dict | None = None, active: bool = True,
) -> int:
    factory = get_session_factory()
    with factory() as db:
        msg = ChatMessage(
            user=user, role=role, content=content,
            meta=json.dumps(meta, ensure_ascii=False) if meta else None,
            active=1 if active else 0,
        )
        db.add(msg)
        db.commit()
        return int(msg.id)


def history(user: str, limit: int | None = None, db: Session | None = None) -> dict:
    """Последние сообщения (по умолчанию chat.history_load_limit) + счётчики."""
    s = load_settings().chat
    limit = limit or s.history_load_limit
    own_db = db is None
    if db is None:
        db = get_session_factory()()
    try:
        total = db.execute(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.user == user)
        ).scalar_one()
        active = db.execute(
            select(func.count()).select_from(ChatMessage)
            .where(ChatMessage.user == user, ChatMessage.active == 1)
        ).scalar_one()
        rows = db.execute(
            select(ChatMessage).where(ChatMessage.user == user)
            .order_by(ChatMessage.id.desc()).limit(limit)
        ).scalars().all()
    finally:
        if own_db:
            db.close()
    items = [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at,
         "meta": json.loads(m.meta) if m.meta else {}}
        for m in reversed(rows)
    ]
    return {"items": items, "total": int(total), "active": int(active)}


def clear_history(user: str) -> int:
    """Удаляет ВСЮ историю пользователя (архив памяти не трогает)."""
    factory = get_session_factory()
    with factory() as db:
        deleted = int(db.execute(delete(ChatMessage).where(ChatMessage.user == user)).rowcount or 0)
        db.commit()
    log_audit(user, "chat_history_cleared", {"deleted": deleted})
    log.info("chat_history_cleared", user=user, deleted=deleted)
    return deleted


# ---------- контекст ----------

def _active_messages(user: str) -> list[ChatMessage]:
    factory = get_session_factory()
    with factory() as db:
        return list(
            db.execute(
                select(ChatMessage)
                .where(ChatMessage.user == user, ChatMessage.active == 1)
                .order_by(ChatMessage.id)
            ).scalars().all()
        )


def context_block(user: str, limit: int) -> str:
    """Текст актуального контекста для репортера («Пользователь: …/Агент: …»).

    Только активные сообщения: после «Очистить контекст» блок пуст —
    заархивированная беседа не занимает контекстное окно.
    """
    msgs = _active_messages(user)
    if not msgs:
        return ""
    lines = [
        f"{_ROLE_LABEL.get(m.role, m.role)}: {m.content}"
        for m in msgs[-max(limit, 1):]
    ]
    return "\n".join(lines)


def _extractive_summary(msgs: list[ChatMessage]) -> tuple[str, str]:
    """Fallback без LLM: памятка из вопросов пользователя."""
    s = load_settings().chat
    questions = [m.content.strip() for m in msgs if m.role == "user" and m.content.strip()]
    if not questions:
        questions = [m.content.strip() for m in msgs if m.content.strip()]
    title = questions[0][: s.archive_title_chars].strip() if questions else "Беседа"
    summary = "; ".join(questions)[: s.context_summary_chars]
    return title or "Беседа", summary or "Беседа без вопросов"


def _llm_summary(msgs: list[ChatMessage]) -> tuple[str, str] | None:
    """Сжатая памятка через LLM (строгий JSON). Сбой → None → fallback."""
    settings = load_settings()
    if settings.llm.provider == "none":
        return None
    block = "\n".join(
        f"{_ROLE_LABEL.get(m.role, m.role)}: {m.content}" for m in msgs
    )[: settings.chat.context_summary_chars]
    prompt = get_prompt("context_summary", messages=block)
    try:
        raw = get_llm().chat(prompt, model=settings.llm.model_main)
        # extract_json переживает <think>, ограждения ```json и текст вокруг JSON
        data = extract_json(raw)
        title = str(data.get("title") or "").strip()[: settings.chat.archive_title_chars]
        summary = str(data.get("summary") or "").strip()
        if not summary:
            raise ValueError("LLM вернул пустую памятку")
        return (title or "Беседа", summary)
    except Exception as exc:  # noqa: BLE001
        log.warning("context_summary_llm_failed", error=str(exc))
        return None


def clear_context(user: str) -> dict:
    """Сворачивает актуальный контекст в памятку (архив памяти).

    Сообщения остаются в истории (active=0) и больше не занимают
    контекстное окно актуального контекста.
    """
    msgs = _active_messages(user)
    if not msgs:
        return {"archived": False, "message": "Актуальный контекст пуст — архивировать нечего"}
    llm_used = False
    summarized = _llm_summary(msgs)
    if summarized is not None:
        llm_used = True
        title, summary = summarized
    else:
        title, summary = _extractive_summary(msgs)
    factory = get_session_factory()
    with factory() as db:
        arc = ContextArchive(
            user=user, title=title, summary=summary, message_count=len(msgs),
        )
        db.add(arc)
        db.execute(
            update(ChatMessage)
            .where(ChatMessage.user == user, ChatMessage.active == 1)
            .values(active=0)
        )
        db.commit()
        archive_id = int(arc.id)
    log_audit(user, "context_archived", {
        "archive_id": archive_id, "messages": len(msgs), "llm": llm_used,
    })
    log.info("context_archived", user=user, archive_id=archive_id, llm=llm_used)
    return {
        "archived": True, "archive_id": archive_id, "title": title,
        "summary": summary, "messages": len(msgs), "llm": llm_used,
    }


def archives(user: str, limit: int | None = None) -> list[dict]:
    s = load_settings().chat
    limit = limit or s.archives_list_limit
    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(
            select(ContextArchive).where(ContextArchive.user == user)
            .order_by(ContextArchive.id.desc()).limit(limit)
        ).scalars().all()
    return [
        {"id": a.id, "title": a.title, "summary": a.summary,
         "message_count": a.message_count, "created_at": a.created_at}
        for a in rows
    ]


# ---------- «вспомни …» — подъём архива по запросу ----------

def _search_terms(question: str, keywords: list[str]) -> list[str]:
    """Значимые слова вопроса для поиска по архиву (без ключевых слов)."""
    s = load_settings().chat
    terms: list[str] = []
    for word in _WORD_RE.findall(question.lower()):
        if len(word) < s.recall_min_word_len:
            continue
        if any(word in k or k in word for k in keywords):
            continue
        if word not in terms:
            terms.append(word)
        if len(terms) >= s.recall_max_terms:
            break
    return terms


def _matching_archives(user: str, terms: list[str]) -> list[dict]:
    s = load_settings().chat
    all_archives = archives(user, limit=s.archives_list_limit)
    if not terms:
        return all_archives[: s.recall_max_archives]
    matched: list[dict] = []
    for arc in all_archives:
        text = (arc["title"] + " " + arc["summary"]).lower()
        if any(term in text for term in terms):
            matched.append(arc)
            if len(matched) >= s.recall_max_archives:
                break
    return matched


def _recall_result(answer: str, matched: list[dict]) -> dict:
    return {
        "answer": answer,
        "files": [],
        "confidence": 0.0,
        "grounded": False,
        "partial": False,
        "filters": {},
        "recall": True,
        "archives": [{"id": a["id"], "title": a["title"]} for a in matched],
    }


def _llm_recall_answer(question: str, block: str) -> str:
    settings = load_settings()
    if settings.llm.provider == "none":
        return ""
    try:
        prompt = get_prompt("context_recall", question=question, archives=block)
        return get_llm().chat(prompt, model=settings.llm.model_main).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("context_recall_llm_failed", error=str(exc))
        return ""


def maybe_recall(user: str, question: str) -> dict | None:
    """Перехватывает запросы вида «вспомни …»: поднимает архив памяти.

    Возвращает ответ в формате /query (с recall=true) или None — если
    вопрос не про память либо архив пуст (тогда обычный поиск по файлам).
    """
    s = load_settings().chat
    low = (question or "").lower()
    if not any(k in low for k in s.recall_keywords):
        return None
    available = archives(user)
    if not available:
        return None  # архив пуст — нечего вспоминать, ищем по документам
    matched = _matching_archives(user, _search_terms(question, s.recall_keywords))
    if not matched:
        titles = "; ".join(f"«{a['title']}»" for a in available[: s.recall_max_archives])
        return _recall_result(
            "В архиве памяти по этому запросу ничего не нашлось. "
            f"В архиве есть: {titles}. Могу поискать факты в загруженных документах — "
            "переформулируйте вопрос.",
            [],
        )
    block = "\n\n".join(
        f"Памятка «{a['title']}» (от {a['created_at']}, сообщений: {a['message_count']}):\n{a['summary']}"
        for a in matched
    )
    answer = _llm_recall_answer(question, block)
    if not answer:
        answer = "\n".join(f"Из архива памяти («{a['title']}»): {a['summary']}" for a in matched)
    return _recall_result(answer, matched)

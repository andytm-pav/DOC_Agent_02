"""Обратная связь («дообучение» агента, v3.0.0).

Пользователь ставит 👍/👎 под ответом и может сразу дать правильный ответ.
Записи хранятся локально в SQLite (feedback_entries) вместе с ВЕКТОРОМ
вопроса (эмбеддинг текущего backend, как у чанков). Никаких привязок к
фразам — совпадение вопросов определяется эмбеддинг-похожестью
(similarity_threshold), поэтому механизм работает на любом языке формулировок.

Как «знания» применяются при ответе:
  1. ИНЖЕКТ ИЗВЕСТНОГО ОТВЕТА (inject_known_answers): если похожий вопрос
     имеет проверенный ответ (corrected_answer или 👍-ответ), он подставляется
     в промпт репортера отдельным блоком — LLM отвечает проверенной строкой
     вместо догадки (паттерн few-shot / RAG-over-feedback, промышленный
     аналог Helpdesk AI «verified answers»).
  2. БУСТ ДОКУМЕНТОВ (boost_documents): файлы, отмеченные 👍 в записях с
     похожим вопросом, получают множитель RRF-score в ретриве (та же логика,
     что у filename_boost) — документы, полезные на этом вопросе, поднимаются.

Пореги/веса — только config.yaml (секция feedback). Администрирование —
админ-вкладка «Обратная связь» (правка/отключение/удаление/пересборка
векторов). Пересборка нужна после смены эмбеддинг-модели (векторы вопросов
должны жить в том же пространстве, что и запросы).
"""
from __future__ import annotations

import json
from array import array
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import FeedbackEntry
from doc_agent.db.session import get_session_factory
from doc_agent.logging import get_logger

log = get_logger("services.feedback")


# ---------- векторы ----------

def _vec_to_bytes(vec: list[float]) -> str:
    """Вектор -> строка (base64-совместимое хранение через array.hex)."""
    return array("f", vec).tobytes().hex()


def _bytes_to_vec(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        buf = bytes.fromhex(raw)
        out = array("f")
        out.frombytes(buf)
        return list(out)
    except ValueError:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if not na or not nb:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def _embed_question(text: str) -> list[float] | None:
    try:
        from doc_agent.vector.embedder import embed_query

        return list(embed_query(text))
    except Exception as exc:  # noqa: BLE001 — сбой эмбеддинга не должен ломать фидбэк
        log.warning("feedback_embed_failed", error=str(exc))
        return None


# ---------- CRUD ----------

def add_or_update(
    user: str, question: str, answer: str, rating: str = "up",
    corrected_answer: str | None = None, file_ids: list[int] | None = None,
) -> dict:
    """Создаёт запись фидбэка; повтор того же вопроса тем же пользователем
    обновляет существующую запись (не плодим дубликаты)."""
    s = load_settings().feedback
    if not s.enabled:
        raise RuntimeError("Обратная связь отключена в конфиге (feedback.enabled)")
    rating = rating if rating in ("up", "down") else "up"
    question = (question or "").strip()[:4000]
    answer = (answer or "").strip()[:20000]
    corrected = (corrected_answer or "").strip()[:20000] or None
    ids = [int(i) for i in (file_ids or []) if str(i).strip().lstrip("-").isdigit()]
    vec = _embed_question(question)

    factory = get_session_factory()
    with factory() as db:
        existing = db.execute(
            select(FeedbackEntry).where(
                FeedbackEntry.user == user, FeedbackEntry.question == question)
        ).scalar_one_or_none()
        if existing is None:
            entry = FeedbackEntry(
                user=user, question=question, answer=answer, rating=rating,
                corrected_answer=corrected,
                file_ids=json.dumps(ids) if ids else None,
                vector=_vec_to_bytes(vec) if vec else None,
                vector_dim=len(vec) if vec else None,
            )
            db.add(entry)
            db.commit()
            entry_id = int(entry.id)
            created = True
        else:
            existing.answer = answer
            existing.rating = rating
            existing.corrected_answer = corrected
            existing.file_ids = json.dumps(ids) if ids else existing.file_ids
            if vec is not None:
                existing.vector = _vec_to_bytes(vec)
                existing.vector_dim = len(vec)
            db.commit()
            entry_id = int(existing.id)
            created = False
    log_audit(user, "feedback_saved", {
        "id": entry_id, "rating": rating, "question": question[:200], "created": created,
    })
    return {"id": entry_id, "created": created}


def list_entries(limit: int = 200, status: str | None = None,
                 db: Session | None = None) -> list[dict]:
    own = db is None
    if db is None:
        db = get_session_factory()()
    try:
        q = select(FeedbackEntry).order_by(FeedbackEntry.id.desc()).limit(max(1, min(limit, 1000)))
        if status:
            q = q.where(FeedbackEntry.status == status)
        rows = db.execute(q).scalars().all()
        return [_entry_dict(e) for e in rows]
    finally:
        if own:
            db.close()


def _entry_dict(e: FeedbackEntry) -> dict:
    try:
        ids = json.loads(e.file_ids or "[]")
    except json.JSONDecodeError:
        ids = []
    return {
        "id": e.id, "user": e.user, "question": e.question, "answer": e.answer,
        "rating": e.rating, "corrected_answer": e.corrected_answer or "",
        "file_ids": ids, "status": e.status, "weight": float(e.weight),
        "uses_count": int(e.uses_count), "last_used_at": e.last_used_at,
        "created_at": e.created_at, "updated_at": e.updated_at,
        "has_vector": bool(e.vector),
    }


def update_entry(entry_id: int, fields: dict, actor: str = "admin") -> dict:
    """Правка записи админом (вопрос/ответ/оценка/статус/вес/файлы)."""
    factory = get_session_factory()
    with factory() as db:
        entry = db.get(FeedbackEntry, entry_id)
        if entry is None:
            raise LookupError(f"Запись фидбэка не найдена: {entry_id}")
        if "question" in fields and str(fields["question"] or "").strip():
            entry.question = str(fields["question"]).strip()[:4000]
            vec = _embed_question(entry.question)
            if vec is not None:
                entry.vector = _vec_to_bytes(vec)
                entry.vector_dim = len(vec)
        if "answer" in fields:
            entry.answer = str(fields["answer"] or "")[:20000]
        if "corrected_answer" in fields:
            entry.corrected_answer = (str(fields["corrected_answer"] or "").strip() or None)
        if "rating" in fields and fields["rating"] in ("up", "down"):
            entry.rating = str(fields["rating"])
        if "status" in fields and fields["status"] in ("active", "disabled"):
            entry.status = str(fields["status"])
        if "weight" in fields:
            try:
                entry.weight = max(0.0, min(float(fields["weight"]), 10.0))
            except (TypeError, ValueError):
                pass
        if "file_ids" in fields:
            ids = [int(i) for i in (fields["file_ids"] or [])
                   if str(i).strip().lstrip("-").isdigit()]
            entry.file_ids = json.dumps(ids) if ids else None
        db.commit()
        out = _entry_dict(entry)
    log_audit(actor, "feedback_updated", {"id": entry_id})
    return out


def delete_entry(entry_id: int, actor: str = "admin") -> None:
    factory = get_session_factory()
    with factory() as db:
        entry = db.get(FeedbackEntry, entry_id)
        if entry is None:
            raise LookupError(f"Запись фидбэка не найдена: {entry_id}")
        db.delete(entry)
        db.commit()
    log_audit(actor, "feedback_deleted", {"id": entry_id})


def reembed_all(actor: str = "admin") -> int:
    """Пересборка векторов вопросов (после смены эмбеддинг-модели)."""
    factory = get_session_factory()
    done = 0
    with factory() as db:
        rows = db.execute(select(FeedbackEntry)).scalars().all()
        for entry in rows:
            vec = _embed_question(entry.question)
            if vec is not None:
                entry.vector = _vec_to_bytes(vec)
                entry.vector_dim = len(vec)
                done += 1
        db.commit()
    log_audit(actor, "feedback_reembed", {"count": done})
    return done


def stats() -> dict:
    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(select(FeedbackEntry)).scalars().all()
    return {
        "total": len(rows),
        "active": sum(1 for r in rows if r.status == "active"),
        "up": sum(1 for r in rows if r.rating == "up"),
        "down": sum(1 for r in rows if r.rating == "down"),
        "with_correction": sum(1 for r in rows if (r.corrected_answer or "").strip()),
        "uses": sum(int(r.uses_count) for r in rows),
    }


# ---------- применение при ответе ----------

def _similar(question: str, db: Session | None = None) -> list[tuple[FeedbackEntry, float]]:
    """Активные записи, похожие на вопрос (косинус >= порога)."""
    s = load_settings().feedback
    if not s.enabled:
        return []
    qvec = _embed_question(question)
    if qvec is None:
        return []
    own = db is None
    if db is None:
        db = get_session_factory()()
    try:
        rows = db.execute(
            select(FeedbackEntry).where(FeedbackEntry.status == "active")
        ).scalars().all()
    finally:
        if own:
            db.close()
    out: list[tuple[FeedbackEntry, float]] = []
    for entry in rows:
        evec = _bytes_to_vec(entry.vector)
        if evec is None or entry.vector_dim != len(qvec):
            continue  # другая размерность = другое векторное пространство
        sim = _cosine(qvec, evec)
        if sim >= s.similarity_threshold:
            out.append((entry, sim))
    out.sort(key=lambda pair: pair[1], reverse=True)
    return out


def known_answers_block(question: str, db: Session | None = None) -> str:
    """Блок «проверенные ответы» для промпта репортера ('' = нет совпадений).

    Берутся записи с corrected_answer; при отсутствии исправлений — 👍-ответ
    как есть (пользователь подтвердил, что ответ правильный). Фактически
    использованные записи помечаются (uses_count/last_used_at).
    """
    s = load_settings().feedback
    if not s.enabled or not s.inject_known_answers:
        return ""
    matches = _similar(question, db)[: max(s.max_inject, 0)]
    if not matches:
        return ""
    blocks: list[str] = []
    used_ids: list[int] = []
    # v3.0.3: лимит длины из конфига (feedback.max_inject_chars, 0 = без
    # лимита) — раньше жёсткие [:3000] резали проверенные ответы с таблицами
    limit = max(int(s.max_inject_chars), 0)
    for entry, sim in matches:
        answer = (entry.corrected_answer or "").strip() or entry.answer.strip()
        if not answer:
            continue
        mark = "исправленный пользователем ответ" if entry.corrected_answer else "подтверждённый ответ"
        blocks.append(f"[{mark} · совпадение {sim:.2f}]\n{answer[:limit] if limit else answer}")
        used_ids.append(int(entry.id))
    if not blocks:
        return ""
    _mark_used(used_ids)
    return "\n\n".join(blocks)


def _mark_used(ids: list[int]) -> None:
    try:
        factory = get_session_factory()
        with factory() as db:
            for entry_id in ids:
                entry = db.get(FeedbackEntry, entry_id)
                if entry is not None:
                    entry.uses_count = int(entry.uses_count) + 1
                    entry.last_used_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("feedback_mark_used_failed", error=str(exc))


def boost_map(question: str, db: Session | None = None) -> dict[int, float]:
    """file_id -> множитель буста ретрива (👍 +, 👎 −), с cap boost_cap."""
    s = load_settings().feedback
    if not s.enabled or not s.boost_documents:
        return {}
    matches = _similar(question, db)
    if not matches:
        return {}
    out: dict[int, float] = {}
    for entry, sim in matches:
        try:
            ids = json.loads(entry.file_ids or "[]")
        except json.JSONDecodeError:
            continue
        sign = 1.0 if entry.rating == "up" else -1.0
        for fid in ids:
            fid = int(fid)
            if fid <= 0:
                continue
            out[fid] = out.get(fid, 0.0) + sign * float(entry.weight) * sim * s.boost_bonus
    cap = max(s.boost_cap, 0.0)
    return {fid: max(-cap, min(bonus, cap)) for fid, bonus in out.items() if abs(bonus) > 0.01}


def apply_boost(fused_scores: dict[int, float], file_by_chunk: dict[int, int],
                question: str) -> list[int]:
    """Мутирует fused_scores (ретривер): множит score чанков «полезных»
    документов. Возвращает список file_id с применённым бустом (для лога)."""
    boosts = boost_map(question)
    if not boosts:
        return []
    applied: list[int] = []
    for cid, score in list(fused_scores.items()):
        fid = file_by_chunk.get(cid) or 0
        bonus = boosts.get(int(fid), 0.0)
        if bonus:
            fused_scores[cid] = score * (1.0 + bonus)
            if int(fid) not in applied:
                applied.append(int(fid))
    return applied

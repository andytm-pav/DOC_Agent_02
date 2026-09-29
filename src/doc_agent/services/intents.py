"""Детерминированные механизмы чата: картотека, подсчёты, поиск по
названиям/типам, подсказки. С v2.6 их ВЫЗЫВАЕТ LLM-планировщик
(services/planner.py), передавая параметры плана (термы, тип документа) —
ключевые слова qa.* остаются только офлайн-fallback'ом (try_service_intent).

Закрывают вопросы, на которые строгий RAG-репортер обязан отвечать
«НЕТ ДАННЫХ» (факты — только из файлов):
  - список файлов из БД (в том числе поиск по словам в НАЗВАНИЯХ файлов);
  - подсчёт по названиям/типам, при нуле — по содержимому чанков;
  - поиск по названиям И типам документов (алиасы doc_type из конфига);
  - подсказка о возможностях (config/prompts/help.txt).

Морфология без ложных совпадений (v2.5): короткие токены и токены с
цифрами («кс2», «23») ищутся ТОЛЬКО точным вхождением — раньше «кс2»
превращался в префикс «к» (матчил всё подряд), а «23» в «2» («№27-2026»).

Здесь же — картотека для промпта репортера (catalog_block) и подсказка
похожих файлов вместо голого «НЕТ ДАННЫХ» (no_data_hint).

Ответ детерминирован и опирается на метаданные файлов (БД), поэтому
помечается grounded=True, confidence=1.0. Ключевые слова, стоп-слова,
алиасы и лимиты — только config.yaml (секция qa); текст подсказки —
config/prompts/help.txt (инлайн-промпты запрещены).

Важно про производительность: load_settings() перечитывает YAML, поэтому
внутри одной обработки вопроса он вызывается один раз, а настройки (s)
передаются в функции явно.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_agent.config import REPO_ROOT, load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import Chunk, File
from doc_agent.logging import get_logger

if TYPE_CHECKING:
    from doc_agent.config import QaSettings

log = get_logger("services.intents")

_WORD_RE = re.compile(r"[а-яёa-z0-9][а-яёa-z0-9\-]*")

_HELP_PATH = REPO_ROOT / "config" / "prompts" / "help.txt"


def _load_help_text() -> str:
    try:
        return _HELP_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def help_text() -> str:
    """Текст подсказки о возможностях (config/prompts/help.txt)."""
    return _load_help_text()


def _filter_type(files: list[File], doc_type: str | None) -> list[File]:
    """Фильтр картотеки по коду doc_type (параметр плана планировщика)."""
    if not doc_type:
        return files
    return [f for f in files if (f.doc_type or "") == doc_type]


# ---------- термы и сопоставление ----------

def name_terms(question: str, exclude_keywords: list[str]) -> list[str]:
    """Значимые слова вопроса для поиска по названиям/типам файлов (без
    ключевых слов и стоп-слов; лимиты из конфига qa.name_*)."""
    s = load_settings().qa
    terms: list[str] = []
    for word in _WORD_RE.findall(question.lower()):
        has_digit = any(ch.isdigit() for ch in word)
        if len(word) < s.name_min_word_len and not has_digit:
            continue  # короткие слова отбрасываем, числа («777») — всегда ищем
        if word in s.name_stopwords:
            continue
        if any(word in k or k in word for k in exclude_keywords):
            continue
        if word not in terms:
            terms.append(word)
        if len(terms) >= s.name_max_terms:
            break
    return terms


def _variants(term: str, s: QaSettings) -> list[str]:
    """Лёгкая морфология без словарей. Токены с цифрами и короткие токены —
    только точное вхождение («кс2», «23»); длинные — плюс префиксы без 1–2
    конечных букв («по вилоновской» -> «вилоновск» найдёт «Вилоновская_…»)."""
    if any(ch.isdigit() for ch in term) or len(term) <= s.name_exact_max_len:
        return [term]
    variants = [term]
    if len(term) >= s.name_exact_max_len + 1:
        variants.append(term[:-1])
    if len(term) >= s.name_exact_max_len + 3:
        variants.append(term[:-2])
    return variants


def _variants_map(terms: list[str], s: QaSettings) -> dict[str, list[str]]:
    return {t: _variants(t, s) for t in terms}


def _file_search_text(f: File, s: QaSettings) -> str:
    """Пространство поиска одного файла: имя + тип (код и алиасы) +
    номера документа/договора + город (всё из конфига, без хардкода)."""
    parts = [f.original_name or "", f.doc_type or ""]
    parts.extend(s.doc_type_aliases.get(f.doc_type or "", []))
    if f.doc_number:
        parts.append(f.doc_number)
    if f.contract_no:
        parts.append(f.contract_no)
    if f.city:
        parts.append(f.city)
    return " ".join(parts).lower()


def match_files(terms: list[str], files: list[File]) -> list[File]:
    """Файлы, у которых в пространстве поиска есть КАЖДЫЙ терм (И-логика)."""
    s = load_settings().qa
    vmap = _variants_map(terms, s)
    matched: list[File] = []
    for f in files:
        text = _file_search_text(f, s)
        if all(any(v in text for v in vmap[t]) for t in terms):
            matched.append(f)
    return matched


def ranked_files(terms: list[str], files: list[File]) -> list[File]:
    """Файлы, отсортированные по числу совпавших термов (для глубокого
    чтения и подсказок: вопрос «сколько листов в смете вилоновской?» не
    должен блокироваться словом «листов», которого в названии нет).
    Порог — qa.deep_read_min_terms (если термов в вопросе меньше — минимум 1)."""
    s = load_settings().qa
    vmap = _variants_map(terms, s)
    min_terms = min(max(s.deep_read_min_terms, 1), max(len(terms), 1))
    scored: list[tuple[int, int, File]] = []
    for f in files:
        text = _file_search_text(f, s)
        score = sum(1 for t in terms if any(v in text for v in vmap[t]))
        if score >= min_terms:
            scored.append((-score, f.id, f))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [f for _, _, f in scored]


def _load_files(db: Session) -> list[File]:
    return list(db.execute(select(File).order_by(File.id)).scalars().all())


# ---------- форматирование ----------

def _type_label(s: QaSettings, doc_type: str | None) -> str:
    return s.doc_type_labels.get(doc_type or "", doc_type or "")


def _file_line(f: File, s: QaSettings) -> str:
    parts = [f.original_name, f"[file_id:{f.id}]"]
    label = _type_label(s, f.doc_type)
    if label:
        parts.append(f"тип: {label}")
    return "• " + " ".join(parts)


def _payload(f: File) -> dict:
    return {"file_id": f.id, "file_name": f.original_name, "doc_type": f.doc_type}


def intent_result(answer: str, files: list[dict], intent: str, question: str) -> dict:
    """Ответ в формате /query от детерминированного механизма (данные из БД,
    поэтому grounded=True, confidence=1.0)."""
    log_audit("query", "query_answered", {
        "q": (question or "")[:200], "intent": intent,
        "files": [f["file_id"] for f in files],
    })
    return {
        "answer": answer,
        "files": files,
        "confidence": 1.0,
        "grounded": True,
        "partial": False,
        "filters": {},
        "intent": intent,
    }


# совместимость со старыми внутренними вызовами
_intent_result = intent_result


def _list_lines(matched: list[File], s: QaSettings, total_hint: str) -> tuple[str, list[dict]]:
    """Общие строки списка: до qa.list_limit файлов + хвост «…и ещё N»."""
    shown = matched[: s.list_limit]
    extra = len(matched) - len(shown)
    lines = [total_hint] + [_file_line(f, s) for f in shown]
    if extra > 0:
        lines.append(f"…и ещё {extra} — полный список во вкладке «Картотека».")
    return "\n".join(lines), [_payload(f) for f in shown]


# ---------- подсчёт по содержимому чанков (fallback) ----------

def _files_by_content(db: Session, terms: list[str], s: QaSettings) -> list[File]:
    """Файлы, в чанках которых встречаются ВСЕ термы (И-логика, по любому
    из вариантов морфологии). Скан ограничен qa.count_content_scan_max_chunks."""
    if not terms:
        return []
    vmap = _variants_map(terms, s)
    need = set(range(len(terms)))
    hit: dict[int, set[int]] = {}
    scanned = 0
    rows = db.execute(select(Chunk.file_id, Chunk.text)).yield_per(2000)
    for fid, text in rows:
        scanned += 1
        if scanned > s.count_content_scan_max_chunks:
            log.warning("count_content_scan_truncated", scanned=scanned)
            break
        t = (text or "").lower()
        for i, term in enumerate(terms):
            if any(v in t for v in vmap[term]):
                hit.setdefault(int(fid), set()).add(i)
    ids = sorted(fid for fid, idxs in hit.items() if need.issubset(idxs))
    by_id = {f.id: f for f in _load_files(db)}
    return [by_id[i] for i in ids if i in by_id]


# ---------- ответы ----------

def list_files_answer(
    question: str, db: Session, terms: list[str] | None = None,
    doc_type: str | None = None,
) -> dict:
    """Список файлов картотеки (весь или по терму/типу).

    terms=None — термы извлекаются из вопроса (офлайн-fallback);
    terms из плана планировщика приоритетнее. doc_type — фильтр типа
    из плана. При doc_type без совпадений — честный ответ «нет таких».
    """
    s = load_settings().qa
    all_files = _load_files(db)
    files = _filter_type(all_files, doc_type)
    total = len(all_files)
    if not total:
        return intent_result(
            "Загруженных файлов пока нет. Перетащите файлы в окно чата "
            "или импортируйте папку на панели «Импорт свалки из папки».",
            [], "list_files", question,
        )
    if doc_type and not files:
        label = _type_label(s, doc_type)
        return intent_result(
            f"Файлов типа «{label}» в картотеке нет. "
            f"Всего загружено файлов: {total}.",
            [], "list_files", question,
        )
    if terms is None:
        terms = name_terms(question, s.list_files_keywords)
    if terms:
        matched = match_files(terms, files)
        if matched:
            text, payloads = _list_lines(
                matched, s, f"По названиям и типам файлов нашлось: {len(matched)}.")
            return intent_result(text, payloads, "list_files", question)
        words = ", ".join(f"«{t}»" for t in terms[:3])
        return intent_result(
            f"Файлов со словом(ами) {words} в названии/типе не нашлось. "
            f"Всего загружено файлов: {total}. Задайте вопрос по содержимому — "
            "агент поищет в текстах документов.",
            [], "list_files", question,
        )
    text, payloads = _list_lines(files, s, f"Сейчас загружено файлов: {total}.")
    text += "\nСпросите по содержимому любого документа — отвечу с цитатами [file_id:N]."
    return intent_result(text, payloads, "list_files", question)


def count_files_answer(
    question: str, db: Session, terms: list[str] | None = None,
    doc_type: str | None = None,
) -> dict:
    """Подсчёт файлов картотеки: всего / по терму / по типу. Параметры
    из плана планировщика (terms/doc_type) приоритетнее вырезания из фразы."""
    s = load_settings().qa
    all_files = _load_files(db)
    files = _filter_type(all_files, doc_type)
    total = len(all_files)
    if not total:
        return intent_result(
            "Загруженных файлов пока нет — считать нечего. Перетащите файлы "
            "в окно чата или импортируйте папку на панели «Импорт свалки».",
            [], "count_files", question,
        )
    if doc_type and not files:
        label = _type_label(s, doc_type)
        return intent_result(
            f"Файлов типа «{label}» в картотеке нет — считать нечего. "
            f"Всего загружено файлов: {total}.",
            [], "count_files", question,
        )
    if terms is None:
        terms = name_terms(question, [])
    if not terms:
        # «сколько файлов обработано?» — всего + разбивка по типам
        by_type: dict[str, int] = {}
        for f in files:
            key = _type_label(s, f.doc_type) or "без типа"
            by_type[key] = by_type.get(key, 0) + 1
        breakdown = ", ".join(f"{k} — {v}" for k, v in sorted(by_type.items()))
        answer = f"Сейчас загружено файлов: {len(files)}."
        if doc_type:
            answer = f"Сейчас загружено файлов типа «{_type_label(s, doc_type)}»: {len(files)}."
        if breakdown:
            answer += f"\nПо типам: {breakdown}."
        if not doc_type:
            answer += ("\nМогу посчитать и по объекту — например: "
                       "«сколько договоров по вилоновской 23?».")
        return intent_result(answer, [], "count_files", question)

    matched = match_files(terms, files)
    via = "По названиям и типам документов"
    if not matched and s.count_content_fallback and not doc_type:
        matched = _files_by_content(db, terms, s)
        via = "По содержимому документов"
    if not matched:
        words = ", ".join(f"«{t}»" for t in terms[:3])
        return intent_result(
            f"Файлов по запросу {words} не нашлось (ни в названиях/типах, "
            f"ни в содержимом). Всего загружено файлов: {total}.",
            [], "count_files", question,
        )
    shown = matched[: s.list_limit]
    lines = [_file_line(f, s) for f in shown]
    if len(matched) > len(shown):
        lines.append(f"…и ещё {len(matched) - len(shown)} — полный список во вкладке «Картотека».")
    answer = f"{via} нашлось: {len(matched)}.\n" + "\n".join(lines)
    return intent_result(answer, [_payload(f) for f in shown], "count_files", question)


def find_files_answer(
    question: str, db: Session, terms: list[str] | None = None,
    doc_type: str | None = None,
) -> dict | None:
    """Поиск файлов по названиям/типам/номерам. None — механизм неприменим,
    вопрос уходит в обычный поиск по содержимому.

    Из плана планировщика: если термов в названиях нет, но указан doc_type —
    возвращаются ВСЕ файлы этого типа (планировщик видит картотеку и знает
    коды типов); если типа нет в картотеке — честный ответ «нет таких».
    """
    s = load_settings().qa
    all_files = _load_files(db)
    files = _filter_type(all_files, doc_type)
    total = len(all_files)
    if terms is None:
        terms = name_terms(question, [])
    matched = match_files(terms, files) if (terms and files) else []
    if matched:
        text, payloads = _list_lines(
            matched, s, f"По названиям и типам файлов нашлось: {len(matched)}.")
        return intent_result(text, payloads, "find_files", question)
    if doc_type:
        label = _type_label(s, doc_type)
        if files:
            text, payloads = _list_lines(
                files, s, f"Файлов типа «{label}» в картотеке: {len(files)}.")
            return intent_result(text, payloads, "find_files", question)
        return intent_result(
            f"Файлов типа «{label}» в картотеке нет. "
            f"Всего загружено файлов: {total}.",
            [], "find_files", question,
        )
    if not terms:
        return None
    # офлайн-fallback: вопрос без файлового домена — обычный поиск (не отвечаем мимо)
    domain = s.file_domain_words + [
        w for words in s.doc_type_aliases.values() for w in words
    ]
    low = (question or "").lower()
    if not any(w in low for w in domain):
        return None  # «покажи все суммы…» — это вопрос по содержимому
    words = ", ".join(f"«{t}»" for t in terms[:3]) or "—"
    return intent_result(
        f"Файлов по запросу {words} в названиях/типах не нашлось. "
        f"Всего загружено файлов: {total}.",
        [], "find_files", question,
    )


# ---------- картотека для промпта репортера ----------

def catalog_block(db: Session) -> str:
    """«Агент знает, какие файлы есть»: список файлов с типом и кратким
    описанием (description классификатора или начало первого чанка).
    Лимиты — qa.catalog_*; строка добавляется в промпт репортера."""
    s = load_settings().qa
    files = _load_files(db)
    if not files:
        return ""
    first_chunk: dict[int, str] = {}
    if any(not (f.description or "").strip() for f in files[: s.catalog_max_files]):
        rows = db.execute(
            select(Chunk.file_id, Chunk.text).where(Chunk.chunk_index == 0)
        ).yield_per(500)
        for fid, text in rows:
            first_chunk[int(fid)] = text or ""
    lines: list[str] = []
    total_chars = 0
    for f in files:
        if len(lines) >= s.catalog_max_files:
            lines.append(f"…и ещё {len(files) - len(lines)} файлов — спросите «покажи все файлы».")
            break
        brief = " ".join(((f.description or "") or first_chunk.get(f.id, "")).split())
        brief = brief[: s.catalog_brief_chars]
        label = _type_label(s, f.doc_type)
        line = f"• {f.original_name} [file_id:{f.id}]"
        if label:
            line += f" — {label}"
        if f.contract_no:
            line += f", договор №{f.contract_no}"
        if brief:
            line += f" — {brief}"
        if total_chars + len(line) > s.catalog_max_chars:
            lines.append(f"…и ещё {len(files) - len(lines)} файлов — спросите «покажи все файлы».")
            break
        total_chars += len(line) + 1
        lines.append(line)
    if not lines:
        return ""
    return "Картотека загруженных файлов:\n" + "\n".join(lines)


# ---------- подсказка вместо голого «НЕТ ДАННЫХ» ----------

def no_data_hint(question: str, db: Session) -> str:
    """Если поиск по содержимому ничего не дал, но по названиям/типам есть
    похожие файлы — предложить прочитать их целиком (глубокое чтение)."""
    s = load_settings().qa
    if not s.no_data_suggest:
        return ""
    terms = name_terms(question, [])
    if not terms:
        return ""
    matched = ranked_files(terms, _load_files(db))[:3]
    if not matched:
        return ""
    lines = [_file_line(f, s) for f in matched]
    first = matched[0].original_name
    return (
        "В картотеке есть похожие файлы:\n" + "\n".join(lines)
        + f"\nСпросите «прочитай файл {first}» — отвечу по его полному тексту."
    )


# ---------- входная точка ----------

def try_service_intent(question: str, db: Session) -> dict | None:
    """Определяет сервисный вопрос по ключевым словам из конфига (qa.*).

    Возвращает ответ в формате /query или None — это не сервисный вопрос,
    нужна обычная обработка (поиск по документам / глубокое чтение).
    """
    s = load_settings().qa
    low = (question or "").lower()
    if not low:
        return None
    if any(k in low for k in s.help_keywords):
        text = _load_help_text()
        if text:
            return _intent_result(text, [], "help", question)

    # доменные слова вопроса (алиасы типов тоже считаются доменом)
    domain = s.file_domain_words + [
        w for words in s.doc_type_aliases.values() for w in words
    ]
    is_domain = any(w in low for w in domain)

    # «сколько файлов…», «сколько договоров по вилоновской 23?»
    if any(k in low for k in s.count_trigger_words) and is_domain:
        return count_files_answer(question, db)

    # «покажи все файлы», «какие файлы есть по …» — раньше find:
    # эти фразы специфичнее (иначе find перехватит «покажи все файлы»)
    if any(k in low for k in s.list_files_keywords):
        return list_files_answer(question, db)

    # «покажи все КС2», «найди файлы по …». С предлогом «по …» перехватываем
    # только при явном файловом слове («найди файлы по марсианской»);
    # «покажи все КС2 по договору 123» — контентный запрос с фильтрами
    if any(k in low for k in s.find_files_keywords):
        has_po_filter = re.search(r"\bпо\s+\S", low) is not None
        has_file_noun = any(w in low for w in s.file_domain_words)
        if not has_po_filter or has_file_noun:
            found = find_files_answer(question, db)
            if found is not None:
                return found

    return None

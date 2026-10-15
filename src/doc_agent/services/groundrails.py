"""Groundrails: grounding-валидация БЕЗ LLM (раздел 7.4/8.2 ТЗ).

- разбивает ответ на утверждения;
- каждое ищет поддержку в top-5 фрагментах;
- неподтверждённые вырезает;
- cut > 30% -> answer.partial=True (E008);
- числовая валидация: числа из источника, иначе утверждение вырезается;
- v3.0.2: Markdown-таблицы не режутся построчно — шапка и разделитель
  '|---|' это РАЗМЕТКА, а не утверждения; они остаются, пока у таблицы
  уцелел хотя бы один ряд данных (раньше шапка вырезалась как
  «неподтверждённая», таблица рассыпалась и переставала рендериться).
- v3.0.3: числа утверждения с цитатами [file_id:N] должны идти из
  ЦИТИРУЕМЫХ файлов (раньше хватало любого фрагмента корпуса — число
  из файла B «подтверждало» утверждение про файл A).
"""
from __future__ import annotations

import re

from doc_agent.config import load_settings
from doc_agent.vector.embedder import tokenize
from doc_agent.vector.stemmer import compat_hits

_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_NUM_RE = re.compile(r"\d[\d\s]{0,20}(?:[.,]\d{1,2})?")
_CITE_RE = re.compile(r"\[file_id:\s*\d+\]")
_CITE_NUM_RE = re.compile(r"\[file_id:\s*(\d+)\]")
# v3.0.2: строка-разделитель GFM-таблицы: '|---|:---:|---|' (пробелы/двоеточия
# допустимы); шапка таблицы под этот шаблон не попадает (там слова).
_TABLE_SEP_RE = re.compile(r"^\|[\s:\-|]+\|?$")
# v3.0.3: фрагмент, состоящий ТОЛЬКО из цитат [file_id:N] (якорь предыдущего
# утверждения, оторвавшийся при разбиении по концу предложения)
_CITE_ONLY_RE = re.compile(r"^(?:\s*\[file_id:\s*\d+\]\s*)+$")


def _split_claims(answer: str) -> list[tuple[str, bool, int | None]]:
    """v3.0.2: разбиение ответа на утверждения с защитой Markdown-таблиц.

    Обычный текст режется как раньше (_SPLIT_RE: конец предложения или
    перевод строки). Подряд идущие строки, начинающиеся с '|', образуют
    БЛОК таблицы: структурные строки блока — шапка (первая строка) и
    разделитель '|---|' — получают structural=True и валидацию grounding
    не проходят (это разметка, а не факты). Раньше каждая строка таблицы
    проверялась как отдельное утверждение: шапка «| № | Файл | Тип |…» не
    находила опоры во фрагментах и вырезалась, а разделитель (пустой
    набор токенов, support=1.0) переживал проверку — в ответ уходила
    «осиротевшая» линия-разделитель, и таблица переставала рендериться.

    Возвращает [(claim, structural, block_id)]; block_id — номер блока
    таблицы (None — вне таблиц). Решение о судьбе структурных строк
    принимает validate_answer: шапка/разделитель остаются только у
    таблиц, у которых уцелел хотя бы один ряд данных.
    """
    out: list[tuple[str, bool, int | None]] = []
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        buf.clear()
        if not text:
            return
        parts = [c.strip() for c in _SPLIT_RE.split(text) if c.strip()]
        for c in parts:
            # v3.0.3: фрагмент из одних цитат после конца предложения —
            # это якорь ПРЕДЫДУЩЕГО утверждения, а не отдельный «факт»:
            # раньше «…итог 100000 руб. [file_id:5]» рвалось на утверждение
            # (без цитаты и лексической опоры) и осиротевший якорь.
            if _CITE_ONLY_RE.match(c) and out and out[-1][2] is None:
                prev = out[-1][0]
                out[-1] = (f"{prev} {c}", False, None)
            else:
                out.append((c, False, None))

    block_id = 0
    lines = answer.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|"):
            flush()
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            rows = [lines[k].strip() for k in range(i, j) if lines[k].strip()]
            for idx, row in enumerate(rows):
                out.append((row, idx == 0 or bool(_TABLE_SEP_RE.match(row)), block_id))
            block_id += 1
            i = j
        else:
            buf.append(line)
            i += 1
    flush()
    return out


def _norm_number(num: str) -> str:
    cleaned = re.sub(r"[^\d,.]", "", num).replace(" ", "").replace(",", ".")
    if cleaned.endswith("."):
        cleaned = cleaned[:-1]
    try:
        val = float(cleaned)
        if val == int(val):
            return str(int(val))
        return f"{val:.10f}".rstrip("0").rstrip(".")
    except (ValueError, OverflowError):
        return cleaned


def _claim_tokens(claim: str) -> list[str]:
    """Токены утверждения с морфологией (v2.7, embeddings.stem_lexical):
    «материалов» и «материал» дают один стемм. Без морфологии grounding
    резал корректные ответы за флексию (старый _prefix_key из 5 букв —
    грубый суррогат)."""
    tokens = [t for t in tokenize(claim) if len(t) > 3]
    if load_settings().embeddings.stem_lexical:
        from doc_agent.vector.stemmer import stem_all

        return stem_all(tokens)
    return tokens


def _source_prefixes(source_text: str) -> set[str]:
    tokens = tokenize(source_text)
    if load_settings().embeddings.stem_lexical:
        from doc_agent.vector.stemmer import stem_all

        tokens = stem_all(tokens)
    return set(tokens)


def _support_ratio(claim: str, source_text: str) -> float:
    claim_tokens = _claim_tokens(claim)
    if not claim_tokens:
        return 1.0
    source = _source_prefixes(source_text)
    # v2.7: счёт с префиксной совместимостью стеммов (см. vector.stemmer):
    # «материалов» в ответе подтверждается «материалом» источника
    return compat_hits(claim_tokens, source) / len(claim_tokens)


def numbers_in(text: str) -> set[str]:
    return {_norm_number(n) for n in _NUM_RE.findall(text) if _norm_number(n)}


def citations_in(text: str) -> set[int]:
    """v3.0.3: file_id из цитат [file_id:N] (публичный хелпер).

    Используется grounding-фильтром и synthesis-гейтом (services.query):
    цитаты — якоря источников, их набор должен совпадать с данными."""
    return {int(m) for m in _CITE_NUM_RE.findall(text)}


def _citation_ok(claim: str, file_ids: set[int]) -> bool:
    """Цитаты [file_id:N] указывают на реальные фрагменты — якорь источника."""
    ids = citations_in(claim)
    return bool(ids) and ids.issubset(file_ids)


def validate_answer(
    answer: str, fragments: list[dict], cut_ratio: float = 0.30, support_threshold: float = 0.55
) -> dict:
    """Возвращает {answer, cut_ratio, partial, grounded}.

    v3.0.2: утверждения из _split_claims (таблицы защищены). Структурные
    строки таблицы (шапка/разделитель) остаются в ответе только если у
    блока уцелел хотя бы один ряд данных; таблица, вырезанная целиком,
    уносит свою разметку с собой (иначе в ответе оставалась бы пустая
    или осиротевшая разметка). Структурные строки не участвуют и в
    вычислении grounded — это разметка, а не утверждения.
    """
    claims = _split_claims(answer)  # (claim, structural, block_id)
    corpus = "\n".join(f["text"] for f in fragments) if fragments else ""
    corpus_nums = numbers_in(corpus)
    fragment_file_ids = {int(f["file_id"]) for f in fragments}
    # v3.0.3: числа по каждому файлу — для привязки «число -> цитируемый файл»
    nums_by_file: dict[int, set[str]] = {}
    for f in fragments:
        fid = int(f["file_id"])
        nums_by_file.setdefault(fid, set()).update(numbers_in(f["text"]))

    def nums_allowed(raw_claim: str, check_claim: str) -> set[str]:
        """Числа, которым разрешено быть в утверждении.

        Утверждения с цитатами [file_id:N] проверяются по числам ИМЕННО
        цитируемых файлов (если такие фрагменты есть); без цитат — по всему
        корпусу как раньше."""
        cited = citations_in(raw_claim)
        if cited and cited.issubset(fragment_file_ids):
            allowed: set[str] = set()
            for fid in cited:
                allowed |= nums_by_file.get(fid, set())
            return allowed
        return corpus_nums

    def grounded_ok(raw_claim: str, check_claim: str) -> bool:
        """Единый предикат подтверждённости (используется в обоих проходах)."""
        best = max((_support_ratio(check_claim, f["text"]) for f in fragments), default=0.0)
        claim_nums = numbers_in(check_claim)
        nums_ok = claim_nums.issubset(nums_allowed(raw_claim, check_claim)) \
            if claim_nums else True
        return best >= support_threshold or (nums_ok and _citation_ok(raw_claim, fragment_file_ids))

    # Проход 1: валидация фактических утверждений; структурные строки
    # откладываются — их судьба зависит от таблицы в целом.
    keep: list[bool] = []
    block_alive: dict[int, bool] = {}
    cut = 0
    for claim, structural, block_id in claims:
        if structural:
            keep.append(False)  # предварительное решение, пересчитаем ниже
            continue
        if claim.strip() == "НЕТ ДАННЫХ":
            keep.append(True)
            continue
        # Маркеры цитирования [file_id:N] — мета-разметка, из проверки исключаем
        check_claim = _CITE_RE.sub("", claim)
        if grounded_ok(claim, check_claim):
            keep.append(True)
            if block_id is not None:
                block_alive[block_id] = True
        else:
            keep.append(False)
            cut += 1

    # Проход 2: сборка в исходном порядке; шапка/разделитель остаются
    # только у живых таблиц (с хотя бы одним уцелевшим рядом данных).
    kept: list[str] = []
    kept_structural: list[bool] = []
    for (claim, structural, block_id), ok in zip(claims, keep):
        if structural:
            if block_id is not None and block_alive.get(block_id):
                kept.append(claim)
                kept_structural.append(True)
            else:
                cut += 1  # таблица вырезана целиком — разметка тоже
            continue
        if ok:
            kept.append(claim)
            kept_structural.append(False)
    ratio = cut / len(claims) if claims else 0.0
    partial = ratio > cut_ratio and len(kept) > 0
    if cut == len(claims) and claims:
        # вырезано всё — фактов нет
        return {"answer": "НЕТ ДАННЫХ", "cut_ratio": 1.0, "partial": False, "grounded": False}
    grounded = all(
        grounded_ok(c, _CITE_RE.sub("", c))
        for c, is_struct in zip(kept, kept_structural)
        if not is_struct and c != "НЕТ ДАННЫХ"
    ) if kept else False
    return {
        "answer": "\n".join(kept).strip(),
        "cut_ratio": round(ratio, 3),
        "partial": partial,
        "grounded": grounded or all(c == "НЕТ ДАННЫХ" for c in kept),
    }

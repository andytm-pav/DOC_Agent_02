"""Groundrails: grounding-валидация БЕЗ LLM (раздел 7.4/8.2 ТЗ).

- разбивает ответ на утверждения;
- каждое ищет поддержку в top-5 фрагментах;
- неподтверждённые вырезает;
- cut > 30% -> answer.partial=True (E008);
- числовая валидация: числа из источника, иначе утверждение вырезается.
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


def _citation_ok(claim: str, file_ids: set[int]) -> bool:
    """Цитаты [file_id:N] указывают на реальные фрагменты — якорь источника."""
    ids = {int(m) for m in _CITE_NUM_RE.findall(claim)}
    return bool(ids) and ids.issubset(file_ids)


def validate_answer(
    answer: str, fragments: list[dict], cut_ratio: float = 0.30, support_threshold: float = 0.55
) -> dict:
    """Возвращает {answer, cut_ratio, partial, grounded}."""
    claims = [c.strip() for c in _SPLIT_RE.split(answer) if c.strip()]
    corpus = "\n".join(f["text"] for f in fragments) if fragments else ""
    corpus_nums = numbers_in(corpus)
    fragment_file_ids = {int(f["file_id"]) for f in fragments}

    kept: list[str] = []
    cut = 0
    for claim in claims:
        if claim.strip() == "НЕТ ДАННЫХ":
            kept.append(claim)
            continue
        # Маркеры цитирования [file_id:N] — мета-разметка, из проверки исключаем
        check_claim = _CITE_RE.sub("", claim)
        best = max((_support_ratio(check_claim, f["text"]) for f in fragments), default=0.0)
        claim_nums = numbers_in(check_claim)
        nums_ok = claim_nums.issubset(corpus_nums) if claim_nums else True
        # Утверждение подтверждено, если:
        #  a) лексическая поддержка >= порога, ИЛИ
        #  б) у утверждения есть цитата на реальный файл и все числа из источника
        supported = best >= support_threshold or (nums_ok and _citation_ok(claim, fragment_file_ids))
        if supported:
            kept.append(claim)
        else:
            cut += 1
    ratio = cut / len(claims) if claims else 0.0
    partial = ratio > cut_ratio and len(kept) > 0
    if cut == len(claims) and claims:
        # вырезано всё — фактов нет
        return {"answer": "НЕТ ДАННЫХ", "cut_ratio": 1.0, "partial": False, "grounded": False}
    grounded = all(
        max((_support_ratio(_CITE_RE.sub("", c), f["text"]) for f in fragments), default=0.0) >= support_threshold
        or (numbers_in(_CITE_RE.sub("", c)).issubset(corpus_nums) and numbers_in(_CITE_RE.sub("", c))
            and _citation_ok(c, fragment_file_ids))
        for c in kept
        if c != "НЕТ ДАННЫХ"
    ) if kept else False
    return {
        "answer": "\n".join(kept).strip(),
        "cut_ratio": round(ratio, 3),
        "partial": partial,
        "grounded": grounded or all(c == "НЕТ ДАННЫХ" for c in kept),
    }

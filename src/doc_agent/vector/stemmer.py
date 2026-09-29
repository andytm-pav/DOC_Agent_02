"""Morphological normalisation of lexical tokens (v2.7).

Industrial basis (web research 09.2026):
  - BM25/dense hybrid search for inflected languages requires normalising
    both the corpus and the query (standard practice in search engines;
    Snowball stemmers — NLTK/PyStemmer/snowballstemmer);
  - in this pipeline, without the stemmer «вилоновской» did not match
    «Вилоновская», and «метериалов» did not match «материалы» — the content
    search on the estimates pulled out extraneous files.

The Snowball Russian stemmer (exact port of the script from snowballstem.org)
is vendored in doc_agent/vendor (pure Python, without dependencies). The
wrapper is thread-safe, with a cache.

The stemmer is used ONLY on lexical mechanisms (BM25, reranker, hashing
embeddings, grounding) and never on real embedding models (api /
sentence_transformers) — they handle morphology themselves, and truncating
words degrades their quality. The embedder.stem_lexical switch is in the
config.
"""
from __future__ import annotations

from functools import lru_cache

from doc_agent.vendor.snowballstemmer import RussianStemmer

_stemmer = RussianStemmer()

# Latin words are truncated by the Porter stemmer from the same family
# (the classic duet for mixed Russian/Latin documents). We keep a small
# dictionary of transliteration-independent service words as is.
_LATIN_OK = {"xlsx", "docx", "pdf", "kg", "kvt", "mm", "m2", "m3"}


@lru_cache(maxsize=65536)
def _stem_cached(word: str) -> str:
    lowered = word.lower()
    if lowered in _LATIN_OK or not lowered.isalpha():
        return lowered
    if all(ord(c) < 0x0400 or ord(c) > 0x04FF for c in lowered):
        # Latin: light truncation of the ending (running/running -> runn)
        # via the same family of algorithms is not vendored — the simplest
        # truncation of the last 'ing'/'ed' is not done: latin rarely affects
        # the scenario of estimates. We return as is.
        return lowered
    return (_stemmer.stemWord(lowered) or lowered).lower()


def stem_token(word: str) -> str:
    """A stem of one token (case is discarded). Deterministic, cached."""
    return _stem_cached(word)


def stem_all(tokens: list[str]) -> list[str]:
    return [stem_token(t) for t in tokens]


# --- v2.7: prefix-compatible matching of stems -------------------------------
# The Snowball RU algorithm is dictionary-free and sometimes "over-truncates"
# individual forms: «материал» (nominative) -> «материа» (the -l verb rule
# fires), while «материалов»/«материалы» -> «материал». This is a known
# property of the algorithm (NLTK/PyStemmer behave the same). Industrial
# compensation: two stems match if one is a prefix of the other. This restores
# consistency of word forms without a lemmatization dictionary.

_MIN_COMPAT = 4


def stems_compatible(a: str, b: str, min_len: int = _MIN_COMPAT) -> bool:
    """Do two stems match (prefix-compatible)? Deterministic, symmetric."""
    if a == b:
        return True
    if len(a) < min_len or len(b) < min_len:
        return False
    return a.startswith(b) or b.startswith(a)


def match_ratio(query_terms: list[str], source_terms: set[str] | list[str]) -> float:
    """Share of query terms that have a compatible stem in source_terms."""
    if not query_terms:
        return 0.0
    src = list(source_terms) if not isinstance(source_terms, set) else source_terms
    hits = 0
    for q in query_terms:
        if q in src or any(stems_compatible(q, s) for s in src):
            hits += 1
    return hits / len(query_terms)


def compat_hits(query_terms: list[str], source_stems: set[str]) -> int:
    """Сколько термов запроса имеют совместимый стемм в source_stems.

    Быстрая версия: если два стемма (обе длиной >= 4) префиксно совместимы,
    их первые 4 символа совпадают — достаточно проверить бакет s[:4].
    """
    if not query_terms:
        return 0
    buckets: dict[str, list[str]] = {}
    for s in source_stems:
        buckets.setdefault(s[:4], []).append(s)
    hits = 0
    for t in query_terms:
        if t in source_stems:
            hits += 1
            continue
        bucket = buckets.get(t[:4])
        if bucket and any(stems_compatible(t, s) for s in bucket):
            hits += 1
    return hits

"""Чанкинг: 512 токенов, overlap 64 (раздел 8.1, шаг 14). Токен ≈ слово/пунктуация.

v2.7: chunk_lines() — табличный чанкинг ПО СТРОКАМ (xlsx/xlsm/csv): чанк
группирует ЦЕЛЫЕ строки до бюджетного размера и никогда не режет строку
посередине (раньше «Унифлекс ЭПП… рул» обрывался на середине, и материал
терялся из виду). Промышленная практика: table/row-aware chunking — строки
таблицы имеют смысл только целиком, с заголовками (contextual retrieval,
Anthropic 2024)."""
from __future__ import annotations

import re

from doc_agent.config import load_settings

_SPLIT_RE = re.compile(r"\S+")


def _token_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _SPLIT_RE.finditer(text)]


def chunk_text(
    text: str, page_spans: list[tuple[int, int]] | None = None
) -> list[dict]:
    """Возвращает чанки [{index, text, page, char_start, char_end}].

    page_spans — список (char_start, page) для определения страницы чанка.
    """
    s = load_settings().chunking
    size, overlap = s.size_tokens, s.overlap_tokens
    spans = _token_spans(text)
    if not spans:
        return []
    chunks: list[dict] = []
    step = max(size - overlap, 1)
    idx = 0
    for start in range(0, len(spans), step):
        window = spans[start : start + size]
        if not window:
            break
        char_start, char_end = window[0][0], window[-1][1]
        page = 1
        if page_spans:
            page = 1
            for cs, pg in page_spans:
                if cs <= char_start:
                    page = pg
                else:
                    break
        chunks.append(
            {
                "index": idx,
                "text": text[char_start:char_end],
                "page": page,
                "char_start": char_start,
                "char_end": char_end,
            }
        )
        idx += 1
        if start + size >= len(spans):
            break
    return chunks


def _line_token_count(line: str) -> int:
    return len(_SPLIT_RE.findall(line))


def chunk_lines(
    text: str,
    preamble: str = "",
    header_line: str | None = None,
) -> list[dict]:
    """Табличный чанкинг: чанки из ЦЕЛЫХ строк текста (v2.7).

    - preamble  — преамбула каждого чанка (обычно «[имя_файла] »,
      chunking.filename_prefix);
    - header_line — шапка таблицы (строка заголовков колонок): повторяется
      первой строкой каждого чанка (chunking.table_header_in_chunk), чтобы
      у LLM и поиска был контекст колонок в любом чанке.

    Возвращает чанки той же структуры, что chunk_text (page всегда 1,
    char_start/char_end не заполняются — строки могли не быть префиксом
    исходного текста). Строки, длиннее размера чанка, НЕ режутся: образуют
    собственный чанк.
    """
    s = load_settings().chunking
    size = s.size_tokens
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    if preamble:
        preamble = preamble if preamble.endswith(" ") else preamble + " "

    chunks: list[dict] = []
    cur: list[str] = []
    cur_tokens = 0

    def flush() -> None:
        nonlocal cur, cur_tokens
        if not cur:
            return
        body = "\n".join(cur)
        if header_line and s.table_header_in_chunk:
            chunks.append({
                "index": len(chunks),
                "text": f"{preamble}{header_line}\n{body}".strip(),
                "page": 1,
                "char_start": 0,
                "char_end": len(body),
            })
        else:
            chunks.append({
                "index": len(chunks),
                "text": f"{preamble}{body}".strip(),
                "page": 1,
                "char_start": 0,
                "char_end": len(body),
            })
        cur, cur_tokens = [], 0

    for line in lines:
        t = _line_token_count(line)
        # шапка повторяется в каждом чанке — резервируем ей место в бюджете
        reserved = _line_token_count(header_line) if (header_line and s.table_header_in_chunk) else 0
        if cur and cur_tokens + t + reserved > size:
            flush()
        cur.append(line)
        cur_tokens += t
        # строка сама длиннее бюджета — выйдет отдельным чанком целиком
        if cur_tokens + reserved >= size:
            flush()
    flush()
    return chunks

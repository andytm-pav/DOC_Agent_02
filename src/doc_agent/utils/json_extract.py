"""Устойчивое извлечение JSON из ответов LLM.

Reasoning-модели (например, glm-4.5-flash / Z.ai и Zhipu) часто возвращают
не «чистый» JSON, а:
  - размышления <think>…<think> до ответа;
  - текст вокруг JSON («Вот результат: …»);
  - ограждения ```json … ```;
  - «висячие» запятые перед } или ];
  - python-стиль (одинарные кавычки, True/False/None).
Строгий json.loads на таком ответе падает («LLM вернул не-JSON»).

extract_json() срезает <think>, находит в тексте ВСЕ сбалансированные
{...} / [...] (с учётом строк и экранирования) и берёт последний
распарсиваемый кандидат — финальный ответ модели обычно идёт последним
(в размышлениях модель может повторять пример из промпта).
"""
from __future__ import annotations

import ast
import json
import re
from typing import Any

_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _balanced_spans(text: str) -> list[str]:
    """Все топ-уровневые сбалансированные фрагменты {...} и [...] в порядке следования."""
    spans: list[str] = []
    depth = 0
    start = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            if depth == 0:
                start = i
            depth += 1
        elif ch in "}]":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    spans.append(text[start:i + 1])
    return spans


def _parse_candidate(cand: str) -> Any:
    """json.loads -> фикс «висячих» запятых -> python-литералы (ast)."""
    try:
        return json.loads(cand)
    except Exception:  # noqa: BLE001
        pass
    try:
        return json.loads(_TRAILING_COMMA_RE.sub(r"\1", cand))
    except Exception:  # noqa: BLE001
        pass
    return ast.literal_eval(cand)  # одинарные кавычки, True/False/None


def extract_json(text: str) -> Any:
    """Достаёт JSON (объект или массив) из ответа LLM.

    Бросает ValueError, если JSON в ответе нет или он не разбирается.
    """
    if not (text or "").strip():
        raise ValueError("пустой ответ LLM")
    cleaned = _THINK_RE.sub("", text)
    candidates = _balanced_spans(cleaned)
    if not candidates:
        raise ValueError("LLM вернул не-JSON (скобки {} или [] не найдены)")
    last_error: Exception | None = None
    for cand in reversed(candidates):
        try:
            return _parse_candidate(cand)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise ValueError(f"LLM вернул не-JSON ({last_error})")

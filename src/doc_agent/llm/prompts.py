"""Загрузка промптов — ТОЛЬКО из config/prompts/*.txt (запрещена инлайн-генерация)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from doc_agent.config import load_settings

_cache: dict[str, str] = {}


def prompts_dir() -> Path:
    return load_settings().config_dir / "prompts"


@lru_cache(maxsize=32)
def _load(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def get_prompt(name: str, **vars: str) -> str:
    """Читает config/prompts/<name>.txt и подставляет {переменные}."""
    path = prompts_dir() / f"{name}.txt"
    key = str(path)
    if key not in _cache:
        _cache[key] = _load(key)
    text = _cache[key]
    for k, v in vars.items():
        text = text.replace("{" + k + "}", v)
    return text

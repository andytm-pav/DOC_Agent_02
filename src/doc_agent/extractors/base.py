"""Базовые типы экстракторов: Protocol Extractor + результат извлечения."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


def node_heading(level: int, text: str, page: int | None = None) -> dict:
    return {"type": "heading", "level": level, "text": text, "page": page}


def node_paragraph(text: str, page: int | None = None) -> dict:
    return {"type": "paragraph", "text": text, "page": page}


def node_table(name: str, rows: list[list[str]], page: int | None = None) -> dict:
    """rows: список строк из ячеек-строк; структура в tree.json — по схеме 5.3."""
    return {
        "type": "table",
        "name": name,
        "rows": [{"cells": [{"text": c, "rowspan": 1, "colspan": 1} for c in row]} for row in rows],
        "page": page,
    }


def node_image(path: str, caption: str = "", page: int | None = None) -> dict:
    return {"type": "image", "path": path, "caption": caption, "page": page}


@dataclass
class ExtractResult:
    text: str = ""
    tree: dict = field(default_factory=dict)
    tables: list[dict] = field(default_factory=list)  # [{"name", "rows": [[str,...]]}]
    pages: int = 1
    ocr_confidence: float | None = None
    unreadable: int = 0
    description: str | None = None  # для description_only-форматов


class Extractor(Protocol):
    def extract(self, path: Path, out_dir: Path) -> ExtractResult: ...


ExtractorFunc = Callable[[Path, Path], ExtractResult]

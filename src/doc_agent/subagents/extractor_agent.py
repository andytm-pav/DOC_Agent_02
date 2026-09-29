"""ExtractorAgent: выбор экстрактора из registry, извлечение text/tree/tables."""
from __future__ import annotations

from pathlib import Path

from doc_agent.extractors.base import ExtractResult
from doc_agent.extractors.registry import get_extractor
from doc_agent.logging import get_logger

log = get_logger("subagent.extractor")


class ExtractorAgent:
    name = "extractor"

    def run(self, fmt: str, path: Path, out_dir: Path) -> ExtractResult:
        extractor = get_extractor(fmt)
        if extractor is None:
            raise RuntimeError(f"Формат не распознан (E001): нет экстрактора для '{fmt}'")
        return extractor(path, out_dir)

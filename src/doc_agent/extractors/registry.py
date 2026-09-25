"""Extractor registry with auto-registration."""

from typing import Any

import structlog

from doc_agent.extractors.base import Extractor, ExtractionResult

logger = structlog.get_logger()

_registry: list[Extractor] = []


def register(extractor: Extractor) -> None:
    """Register an extractor."""
    _registry.append(extractor)
    logger.info("Extractor registered", extractor=type(extractor).__name__)


def get_extractor(format: str) -> Extractor | None:
    """Get an extractor for the given format."""
    for ext in _registry:
        if ext.supports(format):
            return ext
    return None


def extract(file_path: str, format: str) -> ExtractionResult:
    """Extract content from a file using the appropriate extractor."""
    extractor = get_extractor(format)
    if extractor is None:
        raise ValueError(f"No extractor found for format: {format}")
    return extractor.extract(file_path, format)


def auto_register() -> None:
    """Auto-register all built-in extractors."""
    from doc_agent.extractors.office import OfficeExtractor
    from doc_agent.extractors.image import ImageExtractor
    from doc_agent.extractors.email import EmailExtractor
    from doc_agent.extractors.gge import GgeExtractor
    from doc_agent.extractors.archive import ArchiveExtractor

    register(OfficeExtractor())
    register(ImageExtractor())
    register(EmailExtractor())
    register(GgeExtractor())
    register(ArchiveExtractor())

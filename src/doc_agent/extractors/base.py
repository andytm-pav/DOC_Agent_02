"""Base extractor protocol."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ExtractedTable:
    """Extracted table data."""
    name: str
    rows: list[list[str]]


@dataclass
class ExtractedNode:
    """Node in the document tree."""
    type: str  # heading, paragraph, table, image
    text: str = ""
    level: int = 1
    table: ExtractedTable | None = None
    path: str | None = None  # for images
    caption: str | None = None


@dataclass
class ExtractionResult:
    """Result of document extraction."""
    text: str
    tree: list[ExtractedNode] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    pages: int = 1
    unreadable: int = 0
    ocr_confidence: float | None = None


class Extractor(Protocol):
    """Protocol for document extractors."""

    def supports(self, format: str) -> bool:
        """Check if this extractor supports the given format."""
        ...

    def extract(self, file_path: str, format: str) -> ExtractionResult:
        """Extract content from a file."""
        ...

"""Archive extractor (ZIP, RAR, 7Z)."""

import zipfile
from pathlib import Path

import structlog

from doc_agent.extractors.base import ExtractedNode, ExtractionResult

logger = structlog.get_logger()


class ArchiveExtractor:
    """Extractor for archive files."""

    SUPPORTED_FORMATS = {"zip", "rar", "7z"}

    def supports(self, format: str) -> bool:
        return format.lower() in self.SUPPORTED_FORMATS

    def extract(self, file_path: str, format: str) -> ExtractionResult:
        if format.lower() == "zip":
            return self._extract_zip(file_path)
        else:
            # RAR and 7Z would need additional libraries
            return ExtractionResult(text="Archive format requires extraction", tree=[])

    def _extract_zip(self, file_path: str) -> ExtractionResult:
        """List contents of ZIP file."""
        text_parts = []
        with zipfile.ZipFile(file_path, "r") as zf:
            for info in zf.infolist():
                text_parts.append(f"{info.filename} ({info.file_size} bytes)")

        text = "\n".join(text_parts)
        nodes = [ExtractedNode(type="paragraph", text=text)]
        return ExtractionResult(text=text, tree=nodes)

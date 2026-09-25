"""GGE XML extractor (estimates)."""

import xml.etree.ElementTree as ET

import structlog

from doc_agent.extractors.base import ExtractedNode, ExtractedTable, ExtractionResult

logger = structlog.get_logger()


class GgeExtractor:
    """Extractor for GGE XML estimate files."""

    SUPPORTED_FORMATS = {"gge", "xml"}

    def supports(self, format: str) -> bool:
        return format.lower() in self.SUPPORTED_FORMATS

    def extract(self, file_path: str, format: str) -> ExtractionResult:
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            text_parts = []
            tables = []

            # Extract all text content
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    text_parts.append(elem.text.strip())

            text = "\n".join(text_parts)
            nodes = [ExtractedNode(type="paragraph", text=text)]

            return ExtractionResult(text=text, tree=nodes, tables=tables)

        except ET.ParseError as e:
            logger.error("GGE XML parse error", file=file_path, error=str(e))
            return ExtractionResult(text="", tree=[], unreadable=1)

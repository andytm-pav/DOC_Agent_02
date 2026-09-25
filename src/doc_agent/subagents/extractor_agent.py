"""Extractor subagent."""

import structlog

from doc_agent.extractors.registry import extract

logger = structlog.get_logger()


class ExtractorAgent:
    """Extracts content from documents."""

    async def run(self, file_path: str, format: str) -> dict:
        """Extract content from a file."""
        result = extract(file_path, format)

        return {
            "text": result.text,
            "tree": [
                {
                    "type": node.type,
                    "text": node.text,
                    "level": node.level,
                }
                for node in result.tree
            ],
            "tables": [
                {
                    "name": table.name,
                    "rows": table.rows,
                }
                for table in result.tables
            ],
            "pages": result.pages,
            "unreadable": result.unreadable,
            "ocr_confidence": result.ocr_confidence,
        }

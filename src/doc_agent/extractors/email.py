"""Email extractor (EML, MSG)."""

import email
from email import policy
from pathlib import Path

import structlog

from doc_agent.extractors.base import ExtractedNode, ExtractionResult

logger = structlog.get_logger()


class EmailExtractor:
    """Extractor for email files."""

    SUPPORTED_FORMATS = {"eml", "msg"}

    def supports(self, format: str) -> bool:
        return format.lower() in self.SUPPORTED_FORMATS

    def extract(self, file_path: str, format: str) -> ExtractionResult:
        if format.lower() == "eml":
            return self._extract_eml(file_path)
        else:
            raise ValueError(f"Unsupported email format: {format}")

    def _extract_eml(self, file_path: str) -> ExtractionResult:
        """Extract text from EML file."""
        with open(file_path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        subject = msg.get("Subject", "")
        from_addr = msg.get("From", "")
        to_addr = msg.get("To", "")
        date = msg.get("Date", "")

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_content()
                    if isinstance(payload, str):
                        body = payload
                    break
        else:
            payload = msg.get_content()
            if isinstance(payload, str):
                body = payload

        text = f"Тема: {subject}\nОт: {from_addr}\nКому: {to_addr}\nДата: {date}\n\n{body}"
        nodes = [
            ExtractedNode(type="heading", text=subject, level=1),
            ExtractedNode(type="paragraph", text=body),
        ]

        return ExtractionResult(text=text, tree=nodes)

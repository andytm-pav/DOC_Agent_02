"""Image extractor with OCR."""

import structlog
import pytesseract

from doc_agent.extractors.base import ExtractedNode, ExtractionResult

logger = structlog.get_logger()


class ImageExtractor:
    """Extractor for images using OCR."""

    SUPPORTED_FORMATS = {"jpg", "jpeg", "png", "tiff", "bmp"}

    def supports(self, format: str) -> bool:
        return format.lower() in self.SUPPORTED_FORMATS

    def extract(self, file_path: str, format: str) -> ExtractionResult:
        from doc_agent.config import get_settings
        settings = get_settings()

        # Run Tesseract OCR
        data = pytesseract.image_to_data(
            file_path,
            lang="+".join(settings.ocr_tesseract_langs),
            output_type=pytesseract.Output.DICT,
        )

        # Calculate confidence
        confidences = [int(c) for c in data["conf"] if int(c) > 0]
        mean_confidence = sum(confidences) / len(confidences) / 100.0 if confidences else 0.0

        # Extract text
        text_parts = []
        for i, word in enumerate(data["text"]):
            if word.strip():
                text_parts.append(word)

        text = " ".join(text_parts)
        nodes = [ExtractedNode(type="paragraph", text=text)]

        logger.info(
            "OCR completed",
            file=file_path,
            confidence=mean_confidence,
            words=len(text_parts),
        )

        return ExtractionResult(
            text=text,
            tree=nodes,
            ocr_confidence=mean_confidence,
        )

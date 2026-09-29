"""OCR-экстрактор изображений (tesseract | paddle | none — из config)."""
from __future__ import annotations

from pathlib import Path

from doc_agent.config import load_settings
from doc_agent.extractors.base import ExtractResult, node_paragraph
from doc_agent.extractors.registry import register
from doc_agent.logging import get_logger

log = get_logger("extractors.image")


@register("image")
def extract_image(path: Path, out_dir: Path) -> ExtractResult:
    from PIL import Image

    s = load_settings().ocr
    tree: dict = {"version": "1.0", "meta": {"format": "image", "pages": 1}, "children": []}
    img = Image.open(path)

    if s.engine == "none":
        desc = "Изображение: OCR отключён в конфигурации (ocr.engine: none)."
        tree["children"].append(node_paragraph(desc))
        return ExtractResult(text="", tree=tree, pages=1, description=desc)

    if s.engine == "paddle":
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped]

            ocr = PaddleOCR(use_angle_cls=True, lang="ru", show_log=False)
            result = ocr.ocr(str(path), cls=True)
            paddle_lines, paddle_confs = [], []
            for page in result or []:
                for item in page or []:
                    paddle_lines.append(str(item[1][0]))
                    paddle_confs.append(float(item[1][1]))
            text = "\n".join(paddle_lines)
            conf = sum(paddle_confs) / len(paddle_confs) if paddle_confs else None
            for line in paddle_lines:
                tree["children"].append(node_paragraph(line))
            return ExtractResult(text=text, tree=tree, pages=1, ocr_confidence=conf)
        except Exception as exc:  # noqa: BLE001
            log.warning("paddle_unavailable", error=str(exc))
            desc = "PaddleOCR недоступен, текст не распознан."
            tree["children"].append(node_paragraph(desc))
            return ExtractResult(text="", tree=tree, pages=1, description=desc)

    # tesseract (по умолчанию)
    try:
        import pytesseract

        if s.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = s.tesseract_cmd
        langs = "+".join(s.tesseract_langs or ["rus", "eng"])
        data = pytesseract.image_to_data(img, lang=langs, output_type=pytesseract.Output.DICT)
        lines: list[str] = []
        confs: list[float] = []
        current_block, current_line = None, None
        buf: list[str] = []
        for i, word in enumerate(data.get("text", [])):
            word = str(word).strip()
            conf = float(data["conf"][i]) if str(data["conf"][i]).replace(".", "", 1).lstrip("-").isdigit() else -1.0
            block = data.get("block_num", [0])[i]
            line = data.get("line_num", [0])[i]
            if conf >= 0 and word:
                confs.append(conf)
            if (block, line) != (current_block, current_line):
                if buf:
                    lines.append(" ".join(buf))
                buf = [word] if word else []
                current_block, current_line = block, line
            elif word:
                buf.append(word)
        if buf:
            lines.append(" ".join(buf))
        text = "\n".join(line for line in lines if line.strip())
        conf = sum(confs) / len(confs) if confs else None
        for line in text.splitlines():
            tree["children"].append(node_paragraph(line))
        if not text:
            tree["children"].append(node_paragraph("Текст на изображении не распознан."))
        return ExtractResult(text=text, tree=tree, pages=1, ocr_confidence=conf)
    except Exception as exc:  # noqa: BLE001
        # E004-подобная деградация: Tesseract не установлен — файл не падает
        log.warning("tesseract_unavailable", error=str(exc))
        desc = (
            "OCR недоступен: Tesseract не найден. Установите его и укажите путь "
            "в config.yaml: ocr.tesseract_cmd (см. README, раздел OCR)."
        )
        tree["children"].append(node_paragraph(desc))
        return ExtractResult(text="", tree=tree, pages=1, description=desc)

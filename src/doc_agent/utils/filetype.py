"""Определение формата по magic bytes + расширению.

Собственная сигнатурная логика вместо python-magic: libmagic требует
системных библиотек и ломает установку на Windows.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

MAGIC = {
    b"%PDF": "pdf",
    b"\x89PNG": "image",
    b"\xff\xd8\xff": "image",
    b"GIF8": "image",
    b"PK\x03\x04": "zip_container",
    b"D0 CF 11 E0": "legacy_office",  # placeholder, реальная сигнатура ниже
    b"Rar!": "rar",
    b"7z\xbc\xaf\x27\x1c": "7z",
}

_LEGACY_SIG = bytes.fromhex("D0CF11E0A1B11AE1")


def detect_format(path: Path) -> str:
    """Возвращает ключ формата для registry. Бросает RuntimeError, если формат не распознан (E001)."""
    ext = path.suffix.lower().lstrip(".")
    head = path.open("rb").read(512)

    def _is(h: bytes) -> bool:
        return head.startswith(h)

    if _is(b"%PDF"):
        return "pdf"
    if _is(b"\x89PNG") or _is(b"\xff\xd8\xff") or _is(b"GIF8") or _is(b"BM"):
        return "image"
    if _is(b"Rar!"):
        return "rar"
    if _is(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if head.startswith(_LEGACY_SIG):
        return "msg" if ext == "msg" else "doc_legacy"
    if _is(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile:
            raise RuntimeError("ZIP-контейнер повреждён")  # noqa: B904
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        return "zip"
    if head.lstrip().startswith(b"<?xml") or head.lstrip().startswith(b"<"):
        if ext in {"xml", "gge", "amkr", "arps"}:
            return "gge_xml"
        return "gge_xml" if "смет" in head.decode("utf-8", "ignore").lower() else "txt"
    if b"Received:" in head or b"MIME-Version:" in head or (ext == "eml" and b"Subject:" in head):
        return "eml"
    if ext in {"eml"}:
        return "eml"
    if ext in {"csv"}:
        return "csv"
    if ext in {"md"}:
        return "md"
    if ext in {"txt", "log"}:
        return "txt"
    if ext in {"pdf"}:
        return "pdf"
    if ext in {"docx"}:
        return "docx"
    if ext in {"xlsx", "xlsm"}:
        return "xlsx"
    if ext in {"pptx"}:
        return "pptx"
    if ext in {"msg"}:
        return "msg"
    if ext in {"zip"}:
        return "zip"
    if ext in {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff"}:
        return "image"
    if ext in {"7z"}:
        return "7z"
    if ext in {"rar"}:
        return "rar"
    if ext in {"xml"}:
        return "gge_xml"
    # Последний шанс: читаемый текст
    try:
        head.decode("utf-8")
        return "txt"
    except UnicodeDecodeError:
        raise RuntimeError(f"Формат не распознан (E001): {path.name}")  # noqa: B904


IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff"}

"""test_extract.py: каждый формат даёт непустой text (13.2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import KS2_TEXT
from doc_agent.extractors.registry import get_extractor
from doc_agent.utils.filetype import detect_format


def _extract(path: Path, tmp_path: Path):
    fmt = detect_format(path)
    extractor = get_extractor(fmt)
    assert extractor is not None, f"нет экстрактора для {fmt}"
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    return fmt, extractor(path, out_dir)


def test_pdf_text_nonempty(tmp_path: Path, sample_files: dict) -> None:
    fmt, result = _extract(sample_files["pdf"], tmp_path)
    assert fmt == "pdf"
    assert result.text.strip()
    assert "КС-2" in result.text


def test_docx_text_and_table(tmp_path: Path, sample_files: dict) -> None:
    fmt, result = _extract(sample_files["docx"], tmp_path)
    assert fmt == "docx"
    assert result.text.strip()
    assert "КС-2" in result.text
    assert result.tables, "docx должен содержать таблицу 3x3"
    assert len(result.tables[0]["rows"]) == 3
    assert all(len(r) == 3 for r in result.tables[0]["rows"])


def test_xlsx_table(tmp_path: Path, sample_files: dict) -> None:
    fmt, result = _extract(sample_files["xlsx"], tmp_path)
    assert fmt == "xlsx"
    assert result.text.strip()
    assert result.tables


def test_csv(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    p.write_text("Наименование;Сумма\nРаботы;1000\n", encoding="utf-8")
    fmt, result = _extract(p, tmp_path)
    assert fmt == "csv"
    assert result.text.strip()


def test_txt(tmp_path: Path) -> None:
    p = tmp_path / "doc.txt"
    p.write_text(KS2_TEXT, encoding="utf-8")
    fmt, result = _extract(p, tmp_path)
    assert result.text.strip()


def test_eml(tmp_path: Path, sample_files: dict) -> None:
    fmt, result = _extract(sample_files["eml"], tmp_path)
    assert fmt == "eml"
    assert "Счёт-фактура" in result.text


def test_jpg_ocr_or_graceful(tmp_path: Path, sample_files: dict) -> None:
    """Без Tesseract тест пропускается (OCR опционален на машине разработчика)."""
    if "jpg" not in sample_files:
        pytest.skip("PIL недоступен")
    fmt, result = _extract(sample_files["jpg"], tmp_path)
    assert fmt == "image"
    pytesseract = pytest.importorskip("pytesseract")
    import shutil

    if shutil.which("tesseract") is None:
        pytest.skip("Tesseract binary не установлен")
    del pytesseract

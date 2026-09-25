"""Office document extractor (PDF, DOCX, XLSX, PPTX, CSV)."""

from pathlib import Path

import structlog

from doc_agent.extractors.base import ExtractedNode, ExtractedTable, ExtractionResult

logger = structlog.get_logger()


class OfficeExtractor:
    """Extractor for office documents."""

    SUPPORTED_FORMATS = {"pdf", "docx", "xlsx", "pptx", "csv"}

    def supports(self, format: str) -> bool:
        return format.lower() in self.SUPPORTED_FORMATS

    def extract(self, file_path: str, format: str) -> ExtractionResult:
        fmt = format.lower()
        if fmt == "pdf":
            return self._extract_pdf(file_path)
        elif fmt == "docx":
            return self._extract_docx(file_path)
        elif fmt == "xlsx":
            return self._extract_xlsx(file_path)
        elif fmt == "csv":
            return self._extract_csv(file_path)
        else:
            raise ValueError(f"Unsupported office format: {format}")

    def _extract_pdf(self, file_path: str) -> ExtractionResult:
        """Extract text from PDF using kreuzberg."""
        from kreuzberg import extract_text
        text = extract_text(file_path)
        nodes = [ExtractedNode(type="paragraph", text=text)]
        return ExtractionResult(text=text, tree=nodes, pages=1)

    def _extract_docx(self, file_path: str) -> ExtractionResult:
        """Extract text and tables from DOCX."""
        from docx import Document

        doc = Document(file_path)
        nodes: list[ExtractedNode] = []
        tables: list[ExtractedTable] = []
        text_parts: list[str] = []

        for para in doc.paragraphs:
            if para.text.strip():
                nodes.append(ExtractedNode(type="paragraph", text=para.text))
                text_parts.append(para.text)

        for i, table in enumerate(doc.tables):
            rows = []
            for row in table.rows:
                rows.append([cell.text for cell in cells])
            ext_table = ExtractedTable(name=f"Таблица {i + 1}", rows=rows)
            tables.append(ext_table)
            nodes.append(ExtractedNode(type="table", table=ext_table))

        return ExtractionResult(
            text="\n".join(text_parts),
            tree=nodes,
            tables=tables,
        )

    def _extract_xlsx(self, file_path: str) -> ExtractionResult:
        """Extract data from XLSX."""
        from openpyxl import load_workbook

        wb = load_workbook(file_path, read_only=True, data_only=True)
        tables: list[ExtractedTable] = []
        text_parts: list[str] = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([str(cell) if cell is not None else "" for cell in row])
            table = ExtractedTable(name=sheet_name, rows=rows)
            tables.append(table)

            for row in rows:
                text_parts.append(" | ".join(row))

        wb.close()
        return ExtractionResult(
            text="\n".join(text_parts),
            tables=tables,
        )

    def _extract_csv(self, file_path: str) -> ExtractionResult:
        """Extract data from CSV."""
        import csv

        rows = []
        with open(file_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append(row)

        table = ExtractedTable(name="CSV", rows=rows)
        text_parts = [" | ".join(row) for row in rows]
        return ExtractionResult(
            text="\n".join(text_parts),
            tables=[table],
        )

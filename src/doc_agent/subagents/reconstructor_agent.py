"""ReconstructorAgent: воспроизведение документа по tree.json (8.4).

Форматы: docx, xlsx, pdf, html, md.
- docx  -> python-docx
- xlsx  -> openpyxl (каждая таблица — отдельный лист, имя листа = table_name)
- pdf   -> weasyprint (если установлен) иначе reportlab
- html  -> jinja2-рендер
- md    -> markdown
"""
from __future__ import annotations

import html as html_mod
import re
from pathlib import Path
from typing import Any

from doc_agent.logging import get_logger

log = get_logger("subagent.reconstructor")


def _safe_sheet_name(name: str, idx: int) -> str:
    cleaned = re.sub(r"[\[\]\:\*\?\/\\]", "_", (name or f"Таблица{idx}"))[:28]
    return cleaned or f"Таблица{idx}"


def _flat_text(tree: dict) -> str:
    parts: list[str] = []
    for node in tree.get("children", []):
        if node.get("type") in {"heading", "paragraph"}:
            parts.append(node.get("text", ""))
        elif node.get("type") == "table":
            for row in node.get("rows", []):
                parts.append(" | ".join(c.get("text", "") for c in row.get("cells", [])))
    return "\n".join(parts)


class ReconstructorAgent:
    name = "reconstructor"

    def reproduce(self, tree: dict, target_format: str, out_path: Path) -> Path:
        builders = {
            "docx": self._to_docx,
            "xlsx": self._to_xlsx,
            "pdf": self._to_pdf,
            "html": self._to_html,
            "md": self._to_md,
        }
        builder = builders.get(target_format)
        if builder is None:
            raise ValueError(f"Неподдерживаемый формат воспроизведения: {target_format}")
        builder(tree, out_path)
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(f"Не удалось воспроизвести файл: {target_format}")
        return out_path

    def _to_docx(self, tree: dict, out: Path) -> None:
        from docx import Document
        from docx.shared import Pt

        doc = Document()
        for node in tree.get("children", []):
            kind = node.get("type")
            if kind == "heading":
                doc.add_heading(str(node.get("text", "")), level=min(int(node.get("level", 1)), 4))
            elif kind == "paragraph":
                doc.add_paragraph(str(node.get("text", "")))
            elif kind == "table":
                rows = node.get("rows", [])
                if not rows:
                    continue
                ncols = max(len(r.get("cells", [])) for r in rows)
                table = doc.add_table(rows=len(rows), cols=ncols)
                table.style = "Table Grid"
                for ri, row in enumerate(rows):
                    for ci, cell in enumerate(row.get("cells", [])):
                        table.rows[ri].cells[ci].text = str(cell.get("text", ""))
            elif kind == "image" and node.get("path") and Path(node["path"]).exists():
                try:
                    doc.add_picture(node["path"], width=Pt(400))
                except Exception:  # noqa: BLE001
                    log.warning("reproduce_image_skip", path=node["path"])
        doc.save(str(out))

    def _to_xlsx(self, tree: dict, out: Path) -> None:
        from openpyxl import Workbook

        wb = Workbook()
        wb.remove(wb.active)  # type: ignore[arg-type]
        tables = [n for n in tree.get("children", []) if n.get("type") == "table"]
        if not tables:
            ws = wb.create_sheet("Документ")
            ws.cell(row=1, column=1, value=_flat_text(tree)[:32000] or "Нет содержимого")
        for idx, node in enumerate(tables, start=1):
            ws = wb.create_sheet(_safe_sheet_name(node.get("name", ""), idx))
            for ri, row in enumerate(node.get("rows", []), start=1):
                for ci, cell in enumerate(row.get("cells", []), start=1):
                    ws.cell(row=ri, column=ci, value=str(cell.get("text", "")))
        wb.save(str(out))

    def _render_html(self, tree: dict) -> str:
        blocks: list[str] = []
        for node in tree.get("children", []):
            kind = node.get("type")
            esc = html_mod.escape(str(node.get("text", node.get("caption", ""))))
            if kind == "heading":
                blocks.append(f"<h{min(int(node.get('level', 1)), 5)}>{esc}</h{min(int(node.get('level', 1)), 5)}>")
            elif kind == "paragraph":
                blocks.append(f"<p>{esc}</p>")
            elif kind == "table":
                rows_html = []
                for row in node.get("rows", []):
                    cells = "".join(f"<td>{html_mod.escape(str(c.get('text', '')))}</td>" for c in row.get("cells", []))
                    rows_html.append(f"<tr>{cells}</tr>")
                blocks.append(f"<table border='1'>{''.join(rows_html)}</table>")
            elif kind == "image" and node.get("path") and Path(node["path"]).exists():
                blocks.append(f"<img src='file://{node['path']}' width='500'/>")
        return (
            "<html><head><meta charset='utf-8'><title>Документовед</title></head>"
            f"<body>{''.join(blocks)}</body></html>"
        )

    def _to_html(self, tree: dict, out: Path) -> None:
        out.write_text(self._render_html(tree), encoding="utf-8")

    def _to_md(self, tree: dict, out: Path) -> None:
        lines: list[str] = []
        for node in tree.get("children", []):
            kind = node.get("type")
            if kind == "heading":
                lines.append("#" * min(int(node.get("level", 1)), 6) + " " + str(node.get("text", "")))
            elif kind == "paragraph":
                lines.append(str(node.get("text", "")))
            elif kind == "table":
                rows = node.get("rows", [])
                for ri, row in enumerate(rows):
                    cells = [str(c.get("text", "")) for c in row.get("cells", [])]
                    lines.append("| " + " | ".join(cells) + " |")
                    if ri == 0 and len(cells) > 1:
                        lines.append("|" + "|".join(["---"] * len(cells)) + "|")
            elif kind == "image":
                lines.append(f"*[{node.get('caption') or 'изображение'}: {node.get('path', '')}]*")
        out.write_text("\n\n".join(lines), encoding="utf-8")

    def _to_pdf(self, tree: dict, out: Path) -> None:
        # weasyprint 62 (extras [pdf-weasy]) -> reportlab fallback
        try:
            from weasyprint import HTML  # type: ignore[import-untyped]

            HTML(string=self._render_html(tree)).write_pdf(str(out))
            return
        except Exception as exc:  # noqa: BLE001
            log.info("weasyprint_unavailable_reportlab", error=str(exc))
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        styles = getSampleStyleSheet()
        flow: list[Any] = []
        for node in tree.get("children", []):
            kind = node.get("type")
            text = str(node.get("text", ""))
            if kind == "heading":
                flow.append(Paragraph(html_mod.escape(text), styles["Heading2"]))
            elif kind == "paragraph":
                flow.append(Paragraph(html_mod.escape(text), styles["BodyText"]))
            elif kind == "table" and node.get("rows"):
                data = [
                    [Paragraph(html_mod.escape(str(c.get("text", ""))), styles["BodyText"])
                     for c in row.get("cells", [])]
                    for row in node.get("rows", [])
                ]
                t = Table(data)
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, "grey")]))
                flow.append(t)
                flow.append(Spacer(1, 8))
        doc = SimpleDocTemplate(str(out), pagesize=A4)
        doc.build(flow)

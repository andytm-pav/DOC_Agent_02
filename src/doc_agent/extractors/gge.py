"""Сметы ГГЭ / АРПС 1.10 (XML): извлечение структуры и сумм."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from doc_agent.extractors.base import ExtractResult, node_paragraph, node_table
from doc_agent.extractors.registry import register


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@register("gge_xml")
def extract_gge(path: Path, out_dir: Path) -> ExtractResult:
    """XML сметы: обход элементов, текст + ключевые суммы."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise RuntimeError(f"GGE XML не парсится: {exc}") from exc

    children: list[dict] = []
    texts: list[str] = []
    amounts: list[str] = []

    def walk(elem: ET.Element, depth: int) -> None:
        tag = _local(elem.tag)
        text = (elem.text or "").strip()
        interesting = tag.lower() in {
            "name", "caption", "title", "total", "totalcost", "сумма", "итого",
            "amount", "vsego", "cost", "price", "count", "number", "code",
        }
        if text and (interesting or depth <= 3):
            line = f"{tag}: {text}" if not interesting else f"{tag} = {text}"
            children.append(node_paragraph(line))
            texts.append(line)
            if interesting and any(ch.isdigit() for ch in text.replace(" ", "")):
                amounts.append(text)
        for child in elem:
            walk(child, depth + 1)

    walk(root, 0)

    rows = [["Показатель", "Значение"]]
    for item in amounts[:100]:
        tag, _, value = item.partition(" = ")
        rows.append([tag, value])
    if len(rows) > 1:
        children.append(node_table("Смета: суммы", rows))

    text = "\n\n".join(texts)
    tree = {"version": "1.0", "meta": {"format": "gge_xml", "pages": 1}, "children": children}
    desc = "XML-смета (ГГЭ): текст извлечён, структура сохранена."
    return ExtractResult(text=text, tree=tree, tables=[{"name": "Смета: суммы", "rows": rows}], pages=1, description=desc)

"""Почтовые форматы: .eml (stdlib), .msg (опционально extract_msg)."""
from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from doc_agent.extractors.base import ExtractResult, node_paragraph
from doc_agent.extractors.registry import register


@register("eml")
def extract_eml(path: Path, out_dir: Path) -> ExtractResult:
    parser: Any = BytesParser(policy=policy.default)  # type: ignore[arg-type]
    msg: Any = parser.parsebytes(path.read_bytes())
    header = "\n".join(
        [
            f"Тема: {msg.get('subject', '')}",
            f"От: {msg.get('from', '')}",
            f"Кому: {msg.get('to', '')}",
            f"Дата: {msg.get('date', '')}",
        ]
    )
    body = ""
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        content = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            from markdownify import markdownify as md

            body = md(content, strip=["img", "style"])
        else:
            body = str(content)
    text = header + "\n\n" + body
    tree: dict[str, Any] = {
        "version": "1.0",
        "meta": {"format": "eml", "pages": 1},
        "children": [node_paragraph(text)],
    }
    # Вложения — сохранить рядом
    att_dir = out_dir / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for part in msg.iter_attachments():  # type: ignore[attr-defined]
        fn = part.get_filename() or f"attachment_{len(names) + 1}"
        target = att_dir / Path(fn).name
        target.write_bytes(part.get_payload(decode=True) or b"")
        names.append(fn)  # type: ignore[attr-defined]
    if names:
        tree["children"].append(node_paragraph("Вложения: " + ", ".join(names)))
    return ExtractResult(text=text, tree=tree, pages=1)


@register("msg")
def extract_msg(path: Path, out_dir: Path) -> ExtractResult:
    try:
        import extract_msg  # type: ignore[import-untyped]
    except ImportError:
        desc = "MSG-файл: установите extras [msg] (pip install -e .[msg]) для разбора."
        tree = {"version": "1.0", "meta": {"format": "msg", "pages": 1}, "children": [node_paragraph(desc)]}
        return ExtractResult(text="", tree=tree, pages=1, description=desc)
    m = extract_msg.Message(str(path))
    parts = [
        f"Тема: {m.subject or ''}",
        f"От: {m.sender or ''}",
        f"Кому: {m.to or ''}",
        f"Дата: {m.date or ''}",
        "",
        m.body or "",
    ]
    text = "\n".join(parts)
    tree = {"version": "1.0", "meta": {"format": "msg", "pages": 1}, "children": [node_paragraph(text)]}
    return ExtractResult(text=text, tree=tree, pages=1)

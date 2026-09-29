"""Архивы: zip (stdlib), 7z/rar (опциональные extras). Содержимое выводится в картотеку."""
from __future__ import annotations

import zipfile
from pathlib import Path

from doc_agent.extractors.base import ExtractResult, node_paragraph
from doc_agent.extractors.registry import register


@register("zip")
def extract_zip(path: Path, out_dir: Path) -> ExtractResult:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        unsafe = [n for n in names if n.startswith("/") or ".." in n]
        if unsafe:
            raise RuntimeError("Небезопасные пути в архиве")
        unpack_dir = out_dir / "unpacked"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(unpack_dir)
    listing = "\n".join(f"- {n}" for n in names[:200])
    text = f"Архив ZIP, файлов: {len(names)}\n{listing}"
    tree = {"version": "1.0", "meta": {"format": "zip", "pages": 1}, "children": [node_paragraph(text)]}
    result = ExtractResult(text=text, tree=tree, pages=1)
    result.description = "архив"
    return result


@register("7z")
def extract_7z(path: Path, out_dir: Path) -> ExtractResult:
    try:
        import py7zr  # type: ignore[import-untyped]
    except ImportError:
        desc = "7z-архив: установите extras [archive7z] для разбора."
        tree = {"version": "1.0", "meta": {"format": "7z", "pages": 1}, "children": [node_paragraph(desc)]}
        return ExtractResult(text="", tree=tree, pages=1, description=desc)
    with py7zr.SevenZipFile(path) as zf:
        names = zf.getnames()
        unpack_dir = out_dir / "unpacked"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(unpack_dir)
    listing = "\n".join(f"- {n}" for n in names[:200])
    text = f"Архив 7z, файлов: {len(names)}\n{listing}"
    tree = {"version": "1.0", "meta": {"format": "7z", "pages": 1}, "children": [node_paragraph(text)]}
    return ExtractResult(text=text, tree=tree, pages=1, description="архив")


@register("rar")
def extract_rar(path: Path, out_dir: Path) -> ExtractResult:
    try:
        import rarfile  # type: ignore[import-untyped]
    except ImportError:
        desc = "RAR-архив: установите extras [rar] (и unrar) для разбора."
        tree = {"version": "1.0", "meta": {"format": "rar", "pages": 1}, "children": [node_paragraph(desc)]}
        return ExtractResult(text="", tree=tree, pages=1, description=desc)
    with rarfile.RarFile(path) as rf:
        names = [i.filename for i in rf.infolist() if not i.isdir()]
        unpack_dir = out_dir / "unpacked"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        rf.extractall(unpack_dir)
    listing = "\n".join(f"- {n}" for n in names[:200])
    text = f"Архив RAR, файлов: {len(names)}\n{listing}"
    tree = {"version": "1.0", "meta": {"format": "rar", "pages": 1}, "children": [node_paragraph(text)]}
    return ExtractResult(text=text, tree=tree, pages=1, description="архив")

"""Воспроизведение документов (8.4): tree.json -> целевой формат -> download."""
from __future__ import annotations

import json
from pathlib import Path

from doc_agent.db.models import File
from doc_agent.db.session import get_session_factory
from doc_agent.logging import get_logger
from doc_agent.services.jobs import enqueue_reproduce, job_dir_for
from doc_agent.subagents.reconstructor_agent import ReconstructorAgent

log = get_logger("services.reproduce")

ALLOWED_FORMATS = {"docx", "xlsx", "pdf", "html", "md"}
_ext_by_format = {"docx": "docx", "xlsx": "xlsx", "pdf": "pdf", "html": "html", "md": "md"}


def start_reproduce(file_id: int, target_format: str) -> dict:
    if target_format not in ALLOWED_FORMATS:
        raise ValueError(f"target_format должен быть одним из: {sorted(ALLOWED_FORMATS)}")
    factory = get_session_factory()
    with factory() as db:
        f = db.get(File, file_id)
        if f is None:
            raise LookupError("Файл не найден")
        tree_path = Path(f.stored_path).parent / "tree.json"
        if not tree_path.exists():
            # дерево нет (description_only/failed) — строим минимальное из текста
            _fallback_tree(f, tree_path)
        job_id = enqueue_reproduce(file_id, target_format)
    return {"job_id": job_id, "download_url": f"/files/{file_id}/download/{job_id}"}


def _fallback_tree(f: File, tree_path: Path) -> None:
    tree = {
        "version": "1.0",
        "meta": {"file_id": f.id, "format": f.format, "pages": 1},
        "children": [{"type": "paragraph", "text": f.description or f.original_name}],
    }
    tree_path.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")


def finish_reproduce(file_id: int, job_id: int, target_format: str) -> Path:
    """Синхронное построение артефакта (вызывается воркером/роутом при готовности)."""
    factory = get_session_factory()
    with factory() as db:
        f = db.get(File, file_id)
        if f is None:
            raise LookupError("Файл не найден")
        tree_path = Path(f.stored_path).parent / "tree.json"
        if not tree_path.exists():
            _fallback_tree(f, tree_path)
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        out = job_dir_for(f, job_id, _ext_by_format[target_format])
        ReconstructorAgent().reproduce(tree, target_format, out)
        log.info("reproduced", file_id=file_id, job_id=job_id, fmt=target_format)
        return out


def artifact_path(file_id: int, job_id: int, target_format: str) -> Path | None:
    factory = get_session_factory()
    with factory() as db:
        f = db.get(File, file_id)
        if f is None:
            return None
        return job_dir_for(f, job_id, _ext_by_format.get(target_format, target_format))

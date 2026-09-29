"""Разгребание свалки (требование пользователя): агент сам создаёт папку
по указанному пути и раскладывает файлы из свалки по тематическим подпапкам,
названия которых придумывает по содержимому документов.

Настройки — только config/config.yaml (секция sorting), промпт —
config/prompts/sorting.txt (инлайн-промпты запрещены). Без LLM
(provider: none) или при недоступности LLM — детерминированный fallback
из конфига (by_extension | single). По умолчанию файлы КОПИРУЮТСЯ
(свалка не меняется); move_files: true — перемещаются.

Задания выполняются в фоновом потоке, статусы хранятся в памяти процесса
(локальное однопроцессное приложение; после перезапуска список пуст).
"""
from __future__ import annotations

import copy
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

from doc_agent.config import Settings, SortingSettings, load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.extractors.registry import get_extractor
from doc_agent.llm.ollama_client import get_llm
from doc_agent.llm.prompts import get_prompt
from doc_agent.logging import get_logger
from doc_agent.utils.filetype import detect_format
from doc_agent.utils.json_extract import extract_json

log = get_logger("services.sorting")

# Запрещённые в именах папок символы Windows/Linux — платформенное
# ограничение файловой системы, а не настройка, поэтому не в конфиге.
_FS_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ---------- служебные операции над заданием ----------

def _set(job_id: str, **kwargs: object) -> None:
    with _jobs_lock:
        _jobs[job_id].update(kwargs)


def _progress(job_id: str, total: int | None = None, processed: int | None = None) -> None:
    with _jobs_lock:
        if total is not None:
            _jobs[job_id]["progress"]["total"] = total
        if processed is not None:
            _jobs[job_id]["progress"]["processed"] = processed


# ---------- имена папок ----------

def safe_folder_name(raw: str, max_len: int) -> str:
    """Очищает название от запрещённых файловой системой символов (Windows-safe)."""
    name = _FS_UNSAFE.sub(" ", (raw or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:max_len].strip(" .")


def fallback_folder(path: Path, s: SortingSettings) -> str:
    """Детерминированное имя папки, когда LLM отключён или не смог помочь."""
    if s.fallback == "single":
        return s.misc_folder
    ext = path.suffix.lower().lstrip(".")
    if not ext:
        return s.misc_folder
    return s.fallback_folder_template.format(ext=ext.upper())


# ---------- скан свалки (те же предфильтры, что в ingest.scan_folder) ----------

def _scan_dump(path: Path, recursive: bool, settings: Settings) -> tuple[list[Path], dict]:
    s = settings
    max_files = s.sorting.max_files
    exts = {e.lower().lstrip(".") for e in s.ingest.supported_extensions}
    limit_bytes = s.limits.max_file_mb * 1024 * 1024
    counts = {"skipped": 0, "unsupported": 0, "too_large": 0, "truncated": False}
    files: list[Path] = []
    pattern = "**/*" if recursive else "*"
    taken = 0
    for p in sorted(path.glob(pattern)):
        if not p.is_file():
            continue
        name = p.name
        if name.startswith(".") or name.startswith("~$"):
            counts["skipped"] += 1
            continue
        if p.suffix.lower().lstrip(".") not in exts:
            counts["unsupported"] += 1
            continue
        # max_files <= 0 — лимита нет (v2.5: «убрать лимиты»)
        if max_files > 0 and taken >= max_files:
            counts["truncated"] = True
            break
        if p.stat().st_size > limit_bytes:
            counts["too_large"] += 1
            continue
        files.append(p)
        taken += 1
    return files, counts


# ---------- фрагмент текста для определения темы ----------

def _excerpt(path: Path, excerpt_chars: int) -> str:
    """Первые excerpt_chars символов текста документа (без записи артефактов)."""
    try:
        fmt = detect_format(path)
    except RuntimeError:
        return ""
    extractor = get_extractor(fmt)
    if extractor is None:
        return ""
    try:
        with tempfile.TemporaryDirectory() as td:
            result = extractor(path, Path(td))
        return (result.text or "").strip()[:excerpt_chars]
    except Exception as exc:  # noqa: BLE001
        log.debug("sort_excerpt_failed", file=path.name, error=str(exc))
        return ""


# ---------- названия папок через LLM (пакетами, промпт из конфига) ----------

def _llm_names(files: list[Path], excerpts: list[str], settings: Settings) -> dict[int, str]:
    """{index: имя_папки} по LLM. Сбой пакета после retry — fallback для него."""
    s = settings.sorting
    per_file_budget = max(s.batch_max_chars // max(s.batch_size, 1), 1)
    assignments: dict[int, str] = {}
    llm = get_llm()
    for start in range(0, len(files), s.batch_size):
        batch = range(start, min(start + s.batch_size, len(files)))
        items = "\n".join(
            f"{i + 1}. {files[i].name} — {excerpts[i][:per_file_budget].replace(chr(10), ' ')}"
            for i in batch
        )
        prompt = get_prompt("sorting", max_folders=str(s.max_folders), items=items)
        for attempt in range(s.llm_retries + 1):
            try:
                raw = llm.chat(prompt, model=settings.llm.model_main)
                assignments.update(_parse_assignments(raw, set(batch)))
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("sort_llm_batch_failed", attempt=attempt, error=str(exc))
    return assignments


def _parse_assignments(raw: str, valid_idx: set[int]) -> dict[int, str]:
    # extract_json переживает <think>, ограждения ```json и текст вокруг JSON
    # (reasoning-модели вроде glm-4.5-flash так отвечают).
    data = extract_json(raw)
    if isinstance(data, list):  # модель вернула голый массив назначений
        data = {"assignments": data}
    if not isinstance(data, dict):
        raise ValueError("LLM вернул не-JSON объект")
    out: dict[int, str] = {}
    for item in data.get("assignments", []):
        try:
            idx = int(item.get("index")) - 1  # в промпте индексы с 1
        except (TypeError, ValueError):
            continue
        folder = item.get("folder")
        if idx in valid_idx and isinstance(folder, str) and folder.strip():
            out[idx] = folder.strip()
    return out


def _cap_folders(names: dict[int, str], s: SortingSettings) -> dict[int, str]:
    """Если папок больше max_folders — частые остаются, редкие уходят в misc_folder."""
    if len(set(names.values())) <= s.max_folders:
        return names
    by_count: dict[str, int] = {}
    for n in names.values():
        by_count[n] = by_count.get(n, 0) + 1
    keep = {n for n, _ in sorted(by_count.items(), key=lambda kv: (-kv[1], kv[0]))[: s.max_folders]}
    return {i: (n if n in keep else s.misc_folder) for i, n in names.items()}


# ---------- файловые операции ----------

def _resolve_output_root(root: Path, output_path: str | None, s: SortingSettings) -> Path:
    if output_path:
        return Path(output_path).expanduser()
    if root.name:  # рядом со свалкой; для корня диска — внутри самой свалки
        return root.with_name(root.name + s.default_output_suffix)
    return root


def _new_run_dir(out_root: Path, s: SortingSettings) -> Path:
    stamp = datetime.now().strftime(s.run_dir_time_format)
    run_dir = out_root / f"{s.run_dir_prefix}_{stamp}"
    n = 1
    while run_dir.exists():  # коллизия в ту же секунду — крайне маловероятна
        run_dir = out_root / f"{s.run_dir_prefix}_{stamp}_{n}"
        n += 1
    run_dir.mkdir(parents=True)
    return run_dir


def _unique_target(target: Path, template: str) -> Path:
    """Разрешает коллизии имён в одной папке по шаблону duplicate_name_template."""
    if not target.exists():
        return target
    n = 1
    while True:
        cand = target.with_name(template.format(stem=target.stem, n=n, suffix=target.suffix))
        if not cand.exists():
            return cand
        n += 1


# ---------- задание ----------

def sort_folder_start(
    path: str,
    output_path: str | None = None,
    recursive: bool | None = None,
    actor: str = "user",
) -> str:
    """Валидирует пути, создаёт задание и запускает фоновый поток. Возвращает job_id."""
    settings = load_settings()
    if not settings.sorting.enabled:
        raise RuntimeError("Разгребание свалки отключено (sorting.enabled: false)")
    root = Path(path).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"Папка не найдена: {root}")
    if output_path:
        out = Path(output_path).expanduser()
        if out.exists() and not out.is_dir():
            raise NotADirectoryError(f"Путь для результата — не папка: {out}")
    recursive = settings.sorting.recursive if recursive is None else recursive

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id, "state": "running", "phase": "scan",
            "progress": {"total": 0, "processed": 0},
            "result": None, "error": None,
        }
    threading.Thread(
        target=_run_job, args=(job_id, root, output_path, recursive, actor),
        daemon=True, name=f"sort-{job_id[:8]}",
    ).start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return copy.deepcopy(job) if job else None


def list_jobs() -> list[dict]:
    """Все задания разгребания (строка статуса в UI + админ-диагностика)."""
    with _jobs_lock:
        return copy.deepcopy(list(_jobs.values()))


def _run_job(job_id: str, root: Path, output_path: str | None, recursive: bool, actor: str) -> None:
    settings = load_settings()
    s = settings.sorting
    try:
        _set(job_id, phase="scan")
        files, counts = _scan_dump(root, recursive, settings)
        if not files:
            raise RuntimeError(
                "В папке нет поддерживаемых файлов (список расширений — ingest.supported_extensions)"
            )
        _progress(job_id, total=len(files))

        _set(job_id, phase="read")
        excerpts: list[str] = []
        for i, p in enumerate(files):
            excerpts.append(_excerpt(p, s.text_excerpt_chars))
            _progress(job_id, processed=i + 1)

        _set(job_id, phase="name")
        raw_names: dict[int, str] = {}
        if settings.llm.provider != "none":
            raw_names = _llm_names(files, excerpts, settings)
        sanitized = {
            i: clean
            for i, raw in raw_names.items()
            if (clean := safe_folder_name(raw, s.max_folder_name_len))
        }
        sanitized = _cap_folders(sanitized, s)

        _set(job_id, phase="copy")
        out_root = _resolve_output_root(root, output_path, s)
        out_root.mkdir(parents=True, exist_ok=True)
        run_dir = _new_run_dir(out_root, s)

        folders: dict[str, list[dict]] = {}
        errors: list[str] = []
        copied = moved = 0
        for i, src in enumerate(files):
            folder = sanitized.get(i) or fallback_folder(src, s)
            dest_dir = run_dir / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = _unique_target(dest_dir / src.name, s.duplicate_name_template)
            try:
                if s.move_files:
                    shutil.move(str(src), str(target))
                    moved += 1
                else:
                    shutil.copy2(src, target)
                    copied += 1
            except OSError as exc:
                errors.append(f"{src.name}: {exc}")
                continue
            folders.setdefault(folder, []).append({"name": target.name, "source": str(src)})

        llm_named = len(sanitized)
        fallback_used = len(files) - llm_named
        result = {
            "run_dir": str(run_dir),
            "mode": "move" if s.move_files else "copy",
            "llm_named": llm_named,
            "fallback_used": fallback_used,
            "copied": copied,
            "moved": moved,
            "folders": [
                {"folder": name, "count": len(items), "files": items}
                for name, items in sorted(folders.items())
            ],
            "errors": errors,
            "counters": {"total": len(files), "placed": copied + moved, **counts},
        }
        log_audit(actor, "dump_sorted", {
            "path": str(root), "run_dir": str(run_dir), "mode": result["mode"],
            "total": len(files), "placed": copied + moved,
            "llm_named": llm_named, "fallback_used": fallback_used,
            "errors": len(errors),
        })
        log.info("dump_sorted", run_dir=str(run_dir), total=len(files), placed=copied + moved)
        _set(job_id, state="done", result=result)
    except Exception as exc:  # noqa: BLE001
        log.error("sort_job_failed", error=str(exc))
        _set(job_id, state="error", error=str(exc)[:1000])

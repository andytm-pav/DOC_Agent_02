"""Ingest-конвейер (раздел 8.1 ТЗ): dedup по sha256, извлечение, чанки,
эмбеддинги, классификация, связи, статусы.

v2.8 — контекстуальный ретрив (Anthropic, 2024; промышленно +18 п.п.
recall@5 на вопросах-синтезах): в начало КАЖДОГО чанка перед эмбеддингом
и индексацией добавляется контекст: имя документа (+лист), путь заголовков
главы, однострочная заметка о том, чему посвящён документ. Смысл внутри
чанка важнее арифметики размеров."""
from __future__ import annotations

import bisect
import hashlib
import json
import shutil
from pathlib import Path

from sqlalchemy import select

from doc_agent.config import load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import Chunk, File, FileLink, TableFlat
from doc_agent.db.session import get_session_factory
from doc_agent.llm.ollama_client import get_llm
from doc_agent.llm.prompts import get_prompt
from doc_agent.logging import get_logger
from doc_agent.subagents.classifier_agent import ClassifierAgent
from doc_agent.subagents.extractor_agent import ExtractorAgent
from doc_agent.utils.filetype import detect_format
from doc_agent.vector.chroma_client import get_vector_store, make_chunk_key
from doc_agent.vector.chunker import chunk_lines, chunk_text
from doc_agent.vector.embedder import embed_passages

log = get_logger("services.ingest")

_classifier = ClassifierAgent()
_extractor = ExtractorAgent()

# форматы, для которых tree.json не строится — только описание (8.1 шаг 11 / E007)
DESCRIPTION_ONLY_HINTS = ("извещени", "квитанц", "чек ", "чек,", "уведомлени")


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def enqueue_file(tmp_path: Path, original_name: str, source: str = "user") -> dict:
    """Шаги 1-6 (синхронная часть): dedup, хранение, job. Возвращает file_id/message."""
    settings = load_settings()
    limit_mb = settings.limits.max_file_mb
    if tmp_path.stat().st_size > limit_mb * 1024 * 1024:
        raise ValueError(f"Файл больше {limit_mb} МБ (E006)")

    sha = compute_sha256(tmp_path)
    factory = get_session_factory()
    with factory() as db:
        existing = db.execute(select(File).where(File.sha256 == sha)).scalar_one_or_none()
        if existing is not None:
            log_audit("system", "file_dedup", {"file_id": existing.id, "name": original_name})
            return {"file_id": existing.id, "status": existing.status, "message": "Дубликат: файл уже в картотеке", "dedup": True}

        file_dir = settings.app.sub_dir(settings.app.storage_subdir) / sha
        file_dir.mkdir(parents=True, exist_ok=True)
        stored = file_dir / f"original{tmp_path.suffix.lower()}"
        shutil.copy2(tmp_path, stored)

        try:
            fmt = detect_format(stored)
        except RuntimeError as exc:
            f = File(
                sha256=sha, original_name=original_name, stored_path=str(stored), format="unknown",
                size_bytes=stored.stat().st_size, mtime=str(stored.stat().st_mtime),
                status="failed", description=str(exc), source=source,
            )
            db.add(f)
            db.commit()
            log_audit("system", "file_failed", {"name": original_name, "error": str(exc)})
            return {"file_id": f.id, "status": "failed", "message": str(exc)}

        f = File(
            sha256=sha, original_name=original_name, stored_path=str(stored), format=fmt,
            size_bytes=stored.stat().st_size, mtime=str(stored.stat().st_mtime),
            status="pending", source=source,
        )
        db.add(f)
        db.commit()
        file_id = f.id

        from doc_agent.db.models import Job

        job = Job(file_id=file_id, kind="ingest", priority=1)
        db.add(job)
        db.commit()
        log_audit(source, "file_uploaded", {"file_id": file_id, "name": original_name, "format": fmt})
        return {"file_id": file_id, "status": "queued", "message": "Файл принят"}


def remove_file(file_id: int, reason: str, actor: str = "system") -> bool:
    """v3.0.3: удалить файл из картотеки (шаги конвейера откатываются).

    Обратная операция enqueue/process: запись File (+ каскад чанки/таблицы/
    связи/jobs/пути — PRAGMA foreign_keys=ON), векторы Chroma, запись в
    audit_log. Вызывается watcher'ом при реконсилиации (файл удалён/
    изменён на диске, watchdog.on_delete: remove) и доступен тестам.
    Возвращает True, если карточка существовала и удалена.
    """
    factory = get_session_factory()
    with factory() as db:
        f = db.get(File, file_id)
        if f is None:
            return False
        name = f.original_name
        db.delete(f)
        db.commit()
    try:
        get_vector_store().delete_file(file_id)
    except Exception as exc:  # noqa: BLE001 — вектор может быть недоступен
        log.warning("remove_file_vector_failed", file_id=file_id, error=str(exc))
    log_audit(actor, "file_removed", {"file_id": file_id, "name": name, "reason": reason})
    log.info("file_removed", file_id=file_id, name=name, reason=reason)
    return True


def _tree_has_unreadable(tree: dict) -> int:
    return int(tree.get("unreadable", 0) or 0)


# ------------------- v2.8: контекстуальный ретрив -------------------


def _walk_headings(tree: dict) -> list[dict]:
    """Заголовки дерева документа в порядке следования (DFS)."""
    out: list[dict] = []

    def visit(node: dict, depth: int) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "heading":
            out.append({"level": int(node.get("level") or depth or 1),
                        "text": str(node.get("text") or "").strip()})
        for child in node.get("children") or []:
            visit(child, depth + 1)

    visit(tree, 0)
    return out


def heading_path_index(tree: dict, text: str) -> list[tuple[int, str]]:
    """Позиции смены контекста заголовков в плоском тексте документа.

    Возвращает [(char_pos, «Раздел 1 > Подраздел 2»), ...] по возрастанию
    позиций: для каждого заголовка ищем его текст в документе (последовательно,
    от предыдущего найденного) — так чанк по char_start получает путь
    главы, в которой он находится. Заголовки, которых нет в плоском тексте
    (например, названия листов), в индекс не попадают.
    """
    positions: list[tuple[int, str]] = []
    stack: list[tuple[int, str]] = []  # (level, text) — текущая ветка главы
    search_from = 0
    for h in _walk_headings(tree):
        level, htext = h["level"], h["text"]
        if not htext:
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, htext))
        pos = text.find(htext, search_from)
        if pos < 0:
            continue  # заголовка нет в плоском тексте — путь не привязать
        search_from = pos + len(htext)
        path = " > ".join(t for _, t in stack)
        positions.append((pos, path))
    positions.sort(key=lambda x: x[0])
    return positions


def _path_at(index: list[tuple[int, str]], char_start: int) -> str:
    """Путь заголовков, действующий на позиции char_start (последний
    заголовок, начавшийся не позже)."""
    if not index:
        return ""
    pos = bisect.bisect_right([p for p, _ in index], char_start) - 1
    return index[pos][1] if pos >= 0 else ""


def doc_note(f: File, text: str) -> str:
    """Однострочная заметка о документе (v2.8, chunking.context_note).

    1 LLM-вызов на файл (model_light), промпт config/prompts/context_note.txt;
    сбой/офлайн — детерминированный fallback из метаданных классификатора.
    Результат виден и человеку (File.description)."""
    s = load_settings()
    ch = s.chunking
    max_chars = max(ch.note_max_chars, 40)
    if s.llm.provider != "none":
        try:
            prompt = get_prompt("context_note", filename=f.original_name,
                                text=(text or "")[:3000], max_chars=str(max_chars))
            note = get_llm().chat(prompt, model=s.llm.model_light).strip().splitlines()[0]
            note = note.strip(" \"«»").rstrip(".")
            if note:
                return note[:max_chars]
        except Exception as exc:  # noqa: BLE001
            log.warning("context_note_failed", file_id=f.id, error=str(exc))
    # Детерминированный fallback: метаданные классификатора
    parts = [f"Тип: {f.doc_type or 'other'}"]
    for label, val in (("контрагент", f.customer), ("объект", f.city),
                       ("договор", f.contract_no)):
        if val:
            parts.append(f"{label} {val}")
    return "; ".join(parts)[:max_chars]


def build_chunk_prefix(name: str, sheet: str | None, path: str, note: str,
                       enabled: bool = True) -> str:
    """Контекстная преамбула чанка: [имя | Лист: X | Раздел: Y | заметка].

    Имя файла — ПЕРВЫМ элементом (совместимость с v2.6.1-v2.7: чанки
    начинаются с «[<имя файла>»); отсутствующие элементы опускаются.
    enabled=False (chunking.filename_prefix: false) — пустая преамбула."""
    if not enabled:
        return ""
    parts = [name]
    if sheet:
        parts.append(f"Лист: {sheet}")
    if path:
        parts.append(f"Раздел: {path}")
    if note:
        parts.append(note)
    return "[" + " | ".join(parts) + "] "


def process_file(file_id: int) -> None:
    """Фоновые шаги 7-17 (8.1). Вызывается воркером jobs."""
    factory = get_session_factory()
    with factory() as db:
        f = db.get(File, file_id)
        if f is None:
            return
        f.status = "processing"
        db.commit()
        stored = Path(f.stored_path)
        out_dir = stored.parent

        try:
            # 8-9. извлечение
            result = _extractor.run(f.format, stored, out_dir)

            low_text = (result.text or "").lower()
            description_only = (
                result.description is not None
                or any(hint in low_text[:200] for hint in DESCRIPTION_ONLY_HINTS)
            )

            # tree.json (шаг 11: description_only — без дерева)
            if not description_only:
                if not result.tree.get("children"):
                    result.tree = {
                        "version": "1.0",
                        "meta": {"file_id": f.id, "format": f.format, "pages": result.pages},
                        "children": [{"type": "paragraph", "text": result.text or "Пустой документ"}],
                    }
                result.tree.setdefault("meta", {})["file_id"] = f.id
                (out_dir / "tree.json").write_text(
                    json.dumps(result.tree, ensure_ascii=False, indent=1), encoding="utf-8"
                )

            # таблицы в tables_flat
            for tbl in result.tables:
                for ri, row in enumerate(tbl.get("rows", [])):
                    for ci, val in enumerate(row):
                        db.add(TableFlat(file_id=f.id, table_name=tbl.get("name"),
                                         row_index=ri, col_index=ci, value=str(val)))

            # 10. OCR confidence
            f.ocr_confidence = result.ocr_confidence

            # 12-13. классификация
            meta = _classifier.run(result.text or "")
            f.doc_type = meta["doc_type"]
            f.city = meta.get("city")
            f.customer = meta.get("customer")
            f.contract_no = meta.get("contract_no")
            f.contract_date = meta.get("contract_date")
            f.doc_number = meta.get("doc_number")
            f.doc_date = meta.get("doc_date")
            f.amount = meta.get("amount")
            f.description = result.description or (
                f"Тип: {f.doc_type}; символов текста: {len(result.text or '')}"
            )

            # 14-15. чанки + эмбеддинги (не для description_only)
            store = get_vector_store()
            store.delete_file(f.id)
            db.execute(select(Chunk).where(Chunk.file_id == f.id)).scalars().all()
            for old in db.execute(select(Chunk).where(Chunk.file_id == f.id)).scalars().all():
                db.delete(old)
            db.commit()

            if not description_only and (result.text or "").strip():
                page_spans = result.tree.get("meta", {}).get("page_spans")
                ch = load_settings().chunking
                # v2.8: контекстуальный ретрив — заметка о документе (1 LLM-
                # вызов на файл) и путь заголовков главы для каждого чанка.
                note = ""
                if ch.context_note:
                    note = doc_note(f, result.text or "")
                    f.description = note  # заметка — и в карточке файла
                h_index = (heading_path_index(result.tree, result.text or "")
                           if (ch.headings_in_prefix and ch.filename_prefix) else [])
                # v2.7: табличные форматы чанкуются ПО СТРОКАМ (chunk_lines):
                # чанк не режет строку сметы посередине, в преамбуле каждого
                # чанка — имя файла и лист, шапка колонок повторяется в
                # каждом чанке (contextual retrieval). Без преамбулы и шапки
                # строка «Унифлекс ЭПП…» теряла и файл, и смысл колонок.
                if ch.table_aware and f.format in set(ch.table_formats) and result.tables:
                    from doc_agent.extractors.office import table_text_blocks

                    chunks = []
                    for sheet_name, header, body in table_text_blocks(result.tables):
                        preamble = build_chunk_prefix(
                            f.original_name, sheet_name, "", note,
                            enabled=ch.filename_prefix)
                        chunks.extend(
                            chunk_lines(body, preamble=preamble, header_line=header))
                else:
                    chunks = chunk_text(result.text, page_spans)
                    # v2.6.1: преамбула «[имя_файла] » в каждом чанке
                    # (chunking.filename_prefix). Строки смет xlsx сами по
                    # себе не содержат имени объекта/файла — без преамбулы
                    # BM25 и векторный поиск не связывают «вилоновская»
                    # со строками сметы.
                    if ch.filename_prefix:
                        for c in chunks:
                            path = _path_at(h_index, int(c.get("char_start") or 0))
                            c["text"] = build_chunk_prefix(
                                f.original_name, None, path, note) + c["text"]
                embeddings = embed_passages([c["text"] for c in chunks])
                for c, emb in zip(chunks, embeddings):
                    db.add(Chunk(
                        file_id=f.id, chunk_index=c["index"], text=c["text"],
                        page=c.get("page"), char_start=c.get("char_start"), char_end=c.get("char_end"),
                    ))
                db.commit()
                rows = db.execute(select(Chunk).where(Chunk.file_id == f.id)).scalars().all()
                store.upsert_chunks(
                    ids=[make_chunk_key(f.id, c.chunk_index) for c in rows],
                    embeddings=embeddings,
                    documents=[c.text for c in rows],
                    metadatas=[{
                        "file_id": f.id, "chunk_index": c.chunk_index, "page": c.page or 1,
                        "doc_type": f.doc_type or "other",
                        "contract_no": f.contract_no or "", "city": f.city or "",
                    } for c in rows],
                )

            # 16. связи ДС/КС/ТТН/ИД -> договор
            if f.contract_no and f.doc_type in {"ds", "ks2", "ks3", "ks6", "ttn", "id"}:
                contracts = db.execute(
                    select(File).where(File.doc_type == "contract", File.contract_no == f.contract_no)
                ).scalars().all()
                link_type = f"{f.doc_type}_to_contract" if f.doc_type != "contract" else "contract_to_contract"
                for contract in contracts:
                    exists = db.execute(
                        select(FileLink).where(
                            FileLink.parent_id == contract.id, FileLink.child_id == f.id,
                            FileLink.link_type == link_type)
                    ).scalar_one_or_none()
                    if exists is None:
                        db.add(FileLink(parent_id=contract.id, child_id=f.id, link_type=link_type))

            if description_only:
                f.status = "description_only"
            else:
                f.status = "done"
            if _tree_has_unreadable(result.tree) or result.unreadable:
                log.info("ingest_unreadable_elements", file_id=f.id,
                         unreadable=max(_tree_has_unreadable(result.tree), result.unreadable))
            db.commit()
            log_audit("agent:ingest", "file_processed", {"file_id": f.id, "status": f.status, "doc_type": f.doc_type})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            f = db.get(File, file_id)
            if f is not None:
                f.status = "failed"
                f.description = str(exc)[:1000]
                db.commit()
            log_audit("agent:ingest", "file_failed", {"file_id": file_id, "error": str(exc)[:500]})
            log.error("ingest_failed", file_id=file_id, error=str(exc))
            raise


def scan_folder(
    path: str | Path, recursive: bool | None = None, source: str = "folder"
) -> dict:
    """Импорт свалки файлов из указанной пользователем папки.

    Папку можно указать в UI («Импортировать папку») или в конфиге
    ingest.folder_paths. Алгоритм: предфильтр по расширению (конфиг
    ingest.supported_extensions) и служебных имён (.~, ~$), предфильтр
    размера (limits.max_file_mb), далее тот же enqueue_file с dedup по
    sha256, что и при перетаскивании по одному. Обработка — фоновым
    воркером в общем порядке очереди.
    """
    settings = load_settings()
    root = Path(path).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"Папка не найдена: {root}")
    recursive = settings.ingest.recursive if recursive is None else recursive
    max_files = settings.ingest.max_files_per_scan
    exts = {e.lower().lstrip(".") for e in settings.ingest.supported_extensions}
    limit_bytes = settings.limits.max_file_mb * 1024 * 1024

    summary: dict = {
        "path": str(root), "recursive": recursive, "queued": 0, "duplicates": 0,
        "failed": 0, "unsupported": 0, "too_large": 0, "skipped": 0,
        "truncated": False, "errors": [], "file_ids": [],
    }
    scanned = 0
    pattern = "**/*" if recursive else "*"
    for p in sorted(root.glob(pattern)):
        if not p.is_file():
            continue
        name = p.name
        if name.startswith(".") or name.startswith("~$"):
            summary["skipped"] += 1
            continue
        if p.suffix.lower().lstrip(".") not in exts:
            summary["unsupported"] += 1
            continue
        # max_files <= 0 — лимита нет (v2.5: «убрать лимиты»)
        if max_files > 0 and scanned >= max_files:
            summary["truncated"] = True
            break
        scanned += 1
        try:
            if p.stat().st_size > limit_bytes:
                summary["too_large"] += 1
                continue
            res = enqueue_file(p, name, source=source)
        except PermissionError as exc:
            summary["errors"].append(f"{name}: нет доступа ({exc})")
            continue
        except ValueError as exc:  # E006 и др. ограничения приёма
            summary["too_large"] += 1
            summary["errors"].append(f"{name}: {exc}")
            continue
        except OSError as exc:
            summary["errors"].append(f"{name}: {exc}")
            continue
        if res.get("dedup"):
            summary["duplicates"] += 1
            # v3.0.0: путь всё равно запоминаем — агент «знает», где лежит файл
            try:
                from doc_agent.services import fileops as _fileops

                _fileops.remember(int(res["file_id"]), str(p.resolve()), kind="seen")
            except Exception:  # noqa: BLE001 — память путей не ломает импорт
                pass
        elif res.get("status") == "queued":
            summary["queued"] += 1
            summary["file_ids"].append(res["file_id"])
            # v3.0.0: запомнить ОРИГИНАЛЬНОЕ расположение файла на диске —
            # по нему агент даст путь/ссылку и сможет перемещать/копировать
            try:
                from doc_agent.services import fileops as _fileops

                _fileops.remember(int(res["file_id"]), str(p.resolve()), kind="original")
            except Exception:  # noqa: BLE001
                pass
        elif res.get("status") == "failed":
            summary["failed"] += 1

    log_audit(source, "folder_scanned", {
        "path": str(root),
        **{k: v for k, v in summary.items() if k not in {"file_ids", "errors"}},
        "errors": summary["errors"][:5],
    })
    log.info("folder_scanned", path=str(root), queued=summary["queued"],
             duplicates=summary["duplicates"], failed=summary["failed"],
             unsupported=summary["unsupported"])
    return summary


def wait_until_done(file_id: int, timeout_sec: float = 30.0) -> File | None:
    """Хелпер для тестов/CLI: ждём завершения обработки."""
    import time

    factory = get_session_factory()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        with factory() as db:
            f = db.get(File, file_id)
            if f is not None and f.status in {"done", "failed", "description_only"}:
                return f
        time.sleep(0.3)
    return None


def human_message(f: File) -> str:
    """DD-2: «Файл X добавлен в <папка>, распознан как <тип>»."""
    folder = Path(f.stored_path).parent.name
    short = folder[:8]
    doc_type = f.doc_type or "other"
    return f"Файл {f.original_name} добавлен в {short}, распознан как {doc_type}"

"""Файлы на диске: память о путях + sandbox-операции (v3.0.0).

Запрос пользователя: «Агент помнил, где лежат файлы на диске, давал ссылки
по запросу и мог по запросу перемещать/копировать их в другие или новые
папки». Реализация:
  - пути запоминаются в file_locations при импорте папки (оригинальное
    расположение), при операциях агента и вручную в админке;
  - в чате путь/ссылку можно запросить словами — планировщик выбирает
    action file_link (LLM-first: никаких привязок к фразам);
  - операции move/copy/mkdir исполняет планировщик через actions
    file_move/file_copy/file_mkdir; права определяются ГРУППОЙ пользователя
    (users.yaml: permissions files_view/files_manage, allowed_roots).

Безопасность (sandbox): операции возможны ТОЛЬКО с абсолютными путями
внутри разрешённых корней (files.allowed_roots + allowed_roots групп).
Символьные ссылки/.. нейтрализуются Path.resolve(). Каждая операция —
в audit_log. Файлы агента (data/storage) от операций не страдают: копия
в картотеке остаётся (если оперировали оригиналом с диска).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import File, FileLocation
from doc_agent.db.session import get_session_factory
from doc_agent.logging import get_logger
from doc_agent.services import users_store

log = get_logger("services.fileops")


class FileOpsError(RuntimeError):
    """Отказ файловой операции (текст — пользователю, без тех. деталей)."""


# ---------- песочница ----------

def resolve_safe(path: str, roots: list[Path]) -> Path:
    """Абсолютный путь ВНУТРИ одного из корней; иначе FileOpsError."""
    raw = (path or "").strip().strip('"')
    if not raw:
        raise FileOpsError("Путь не указан")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise FileOpsError("Путь должен быть абсолютным (например D:/Документы)")
    resolved = p.resolve()
    for root in roots:
        if resolved == root or root in resolved.parents:
            return resolved
    raise FileOpsError(
        "Путь вне разрешённых папок. Разрешённые корни настраиваются "
        "администратором (config files.allowed_roots и группы в users.yaml)."
    )


def allowed_roots(actor: str | None) -> list[Path]:
    roots = users_store.allowed_roots_for(actor or "")
    return [r.resolve() for r in roots if r.is_absolute()]


def roots_summary(actor: str | None) -> str:
    roots = allowed_roots(actor)
    return "; ".join(str(r) for r in roots) if roots else "(не заданы)"


# ---------- память о путях ----------

def remember(file_id: int, path: str, kind: str = "original",
             is_current: bool = True, actor: str = "system") -> None:
    """Запомнить путь файла (старые актуальные помечаются устаревшими)."""
    factory = get_session_factory()
    with factory() as db:
        if is_current:
            db.execute(
                update(FileLocation)
                .where(FileLocation.file_id == file_id, FileLocation.is_current == 1)
                .values(is_current=0)
            )
        db.add(FileLocation(file_id=file_id, path=str(path), kind=kind,
                            is_current=1 if is_current else 0))
        db.commit()
    log.debug("file_location_remembered", file_id=file_id, kind=kind, actor=actor)


def locations_for(file_id: int, db: Session | None = None) -> list[dict]:
    own = db is None
    if db is None:
        db = get_session_factory()()
    try:
        rows = db.execute(
            select(FileLocation).where(FileLocation.file_id == file_id)
            .order_by(FileLocation.is_current.desc(), FileLocation.id.desc())
        ).scalars().all()
        return [{"id": r.id, "path": r.path, "kind": r.kind,
                 "is_current": bool(r.is_current), "created_at": r.created_at}
                for r in rows]
    finally:
        if own:
            db.close()


def current_path(file_id: int, db: Session | None = None) -> Path | None:
    """Актуальный путь файла на диске (существующий) или None."""
    for loc in locations_for(file_id, db):
        if loc["is_current"]:
            p = Path(loc["path"])
            if p.exists():
                return p
    return None


def search_locations(terms: list[str], limit: int = 20,
                     db: Session | None = None) -> list[dict]:
    """Поиск запомненных путей по подстрокам (для file_link по термам)."""
    own = db is None
    if db is None:
        db = get_session_factory()()
    try:
        rows = db.execute(
            select(FileLocation, File.original_name)
            .join(File, File.id == FileLocation.file_id, isouter=True)
            .where(FileLocation.is_current == 1)
            .order_by(FileLocation.id.desc()).limit(2000)
        ).all()
    finally:
        if own:
            db.close()
    lowered = [t.lower() for t in terms if t]
    out: list[dict] = []
    for loc, name in rows:
        haystack = (loc.path + " " + (name or "")).lower()
        if not lowered or any(t in haystack for t in lowered):
            out.append({"file_id": loc.file_id, "file_name": name or "",
                        "path": loc.path, "kind": loc.kind})
            if len(out) >= limit:
                break
    return out


def file_ids_at(path: str, db: Session | None = None) -> list[int]:
    """v3.0.3: file_id карточек, чей АКТУАЛЬНЫЙ путь равен данному.

    Используется реконсилиацией watcher'а: файл на диске удалён/изменён —
    находим карточки, которые «живут» по этому пути (file_locations,
    is_current=1, точное совпадение строки пути)."""
    own = db is None
    if db is None:
        db = get_session_factory()()
    try:
        rows = db.execute(
            select(FileLocation.file_id).where(
                FileLocation.path == str(path), FileLocation.is_current == 1)
        ).scalars().all()
        return sorted({int(r) for r in rows})
    finally:
        if own:
            db.close()


def forget_path(path: str, actor: str = "system") -> int:
    """v3.0.3: пометить путь устаревшим (is_current=0) у всех карточек.

    Агент перестаёт считать файл лежащим по этому пути (file_link больше
    не даёт мёртвых ссылок), карточка с содержимым ОСТАЁТСЯ в картотеке —
    копия в data/storage не зависит от судьбы оригинала. Возвращает число
    помеченных записей."""
    factory = get_session_factory()
    with factory() as db:
        res = db.execute(
            update(FileLocation)
            .where(FileLocation.path == str(path), FileLocation.is_current == 1)
            .values(is_current=0)
        )
        db.commit()
        marked = int(res.rowcount or 0)
    if marked:
        log_audit(actor, "file_path_forgotten", {"path": str(path), "marked": marked})
        log.info("file_path_forgotten", path=str(path), marked=marked)
    return marked


# ---------- операции ----------

def _file_name_for(file_id: int, db: Session) -> str:
    f = db.get(File, file_id)
    return f.original_name if f is not None else f"file_{file_id}"


def _stored_path(file_id: int, db: Session) -> Path | None:
    f = db.get(File, file_id)
    if f is None:
        return None
    p = Path(f.stored_path)
    return p if p.exists() else None


def make_dir(path: str, actor: str | None, create_parents: bool = True) -> Path:
    """Создать папку внутри разрешённых корней."""
    if not load_settings().files.enabled:
        raise FileOpsError("Файловые операции отключены в конфиге (files.enabled)")
    roots = allowed_roots(actor)
    target = resolve_safe(path, roots)
    target.mkdir(parents=create_parents, exist_ok=True)
    log_audit(actor or "system", "file_mkdir", {"path": str(target)})
    log.info("file_mkdir", path=str(target), actor=actor)
    return target


def _prepare_dest(dest_dir: str, actor: str | None, create: bool) -> Path:
    roots = allowed_roots(actor)
    if not roots:
        raise FileOpsError(
            "Файловые операции запрещены: не заданы разрешённые корни "
            "(config files.allowed_roots или allowed_roots группы в users.yaml)."
        )
    dest = resolve_safe(dest_dir, roots)
    if not dest.exists():
        if not create:
            raise FileOpsError(f"Папка не существует: {dest}")
        dest.mkdir(parents=True, exist_ok=True)
    if not dest.is_dir():
        raise FileOpsError(f"Назначение не папка: {dest}")
    return dest


def _unique_dest(dest_dir: Path, name: str) -> Path:
    """Коллизии имён: «имя (2).ext» (как в sorting.duplicate_name_template)."""
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    for n in range(2, 1000):
        candidate = dest_dir / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
    raise FileOpsError("Не удалось подобрать имя файла в папке назначения")


def _check_source(src: Path) -> None:
    limit_mb = load_settings().files.max_move_mb
    size_mb = src.stat().st_size / (1024 * 1024)
    if size_mb > limit_mb:
        raise FileOpsError(f"Файл больше лимита {limit_mb} МБ ({size_mb:.0f} МБ)")


def move_file(file_id: int, dest_dir: str, actor: str | None,
              create_dest: bool = True) -> dict:
    """Переместить файл (оригинал с запомненного пути, иначе копию из
    картотеки агента) в папку назначения. Обновляет память о путях."""
    if not load_settings().files.enabled:
        raise FileOpsError("Файловые операции отключены в конфиге (files.enabled)")
    factory = get_session_factory()
    with factory() as db:
        name = _file_name_for(file_id, db)
        src = current_path(file_id, db)
        exported = False
        if src is None:
            src = _stored_path(file_id, db)  # копия из хранилища агента
            exported = True
        if src is None:
            raise FileOpsError("Файл не найден ни по запомненному пути, ни в картотеке агента")
        dest_dir_p = _prepare_dest(dest_dir, actor, create_dest)
        _check_source(src)
        target = _unique_dest(dest_dir_p, name)
        shutil.move(str(src), str(target))
        if not exported:
            remember(file_id, str(target), kind="moved", actor=actor or "system")
        else:
            remember(file_id, str(target), kind="exported", actor=actor or "system")
        log_audit(actor or "system", "file_moved", {
            "file_id": file_id, "from": str(src), "to": str(target),
        })
        log.info("file_moved", file_id=file_id, src=str(src), dst=str(target), actor=actor)
        return {"file_id": file_id, "from": str(src), "to": str(target),
                "exported_from_agent": exported}


def copy_file(file_id: int, dest_dir: str, actor: str | None,
              create_dest: bool = True) -> dict:
    """Скопировать файл в папку назначения (оригинал остаётся на месте)."""
    if not load_settings().files.enabled:
        raise FileOpsError("Файловые операции отключены в конфиге (files.enabled)")
    factory = get_session_factory()
    with factory() as db:
        name = _file_name_for(file_id, db)
        src = current_path(file_id, db)
        from_agent = False
        if src is None:
            src = _stored_path(file_id, db)
            from_agent = True
        if src is None:
            raise FileOpsError("Файл не найден ни по запомненному пути, ни в картотеке агента")
        dest_dir_p = _prepare_dest(dest_dir, actor, create_dest)
        _check_source(src)
        target = _unique_dest(dest_dir_p, name)
        shutil.copy2(src, target)
        remember(file_id, str(target), kind="copied", actor=actor or "system")
        log_audit(actor or "system", "file_copied", {
            "file_id": file_id, "from": str(src), "to": str(target),
        })
        log.info("file_copied", file_id=file_id, src=str(src), dst=str(target), actor=actor)
        return {"file_id": file_id, "from": str(src), "to": str(target),
                "copied_from_agent": from_agent}


def file_link_block(terms: list[str], file_ids: list[int],
                    db: Session) -> tuple[str, list[dict]]:
    """Блок «где лежат файлы» для ответа в чате (action file_link).

    v3.0.1 (баг: «покажи путь, где лежат ЭТИ договора» выдавал пути
    посторонних файлов): раньше при пустых file_ids и terms возвращались
    ПОСЛЕДНИЕ запомненные пути любых файлов — выглядит как ответ, хотя
    файлы не те. Теперь:
      1) file_ids (из контекста беседы, правило планировщика) — точный
         ответ по этим файлам;
      2) terms — запомненные пути по термам + файлы картотеки, найденные
         ПО НАЗВАНИЯМ (даже если путь не запомнен — честное «путь не
         запомнен» по ПРАВИЛЬНЫМ файлам);
      3) иначе — честное «не удалось определить, о каких файлах речь»,
         никаких случайных путей.
    """
    rows: list[dict] = []
    if file_ids:
        for fid in file_ids[:10]:
            cur = current_path(fid, db)
            name = _file_name_for(fid, db)
            if cur is not None:
                rows.append({"file_id": fid, "file_name": name, "path": str(cur), "kind": "known"})
            else:
                rows.append({"file_id": fid, "file_name": name, "path": "", "kind": "unknown"})
    elif terms:
        # v3.0.1: сначала запомненные пути по термам...
        rows = search_locations(terms, limit=10, db=db)
        # ...затем файлы картотеки по названиям (путь может быть не
        # запомнен — но пользователь должен увидеть именно ЕГО файлы)
        from doc_agent.services.intents import _load_files, match_files

        known = {r["file_id"] for r in rows}
        for f in match_files(terms, _load_files(db))[:10]:
            if f.id in known:
                continue
            rows.append({"file_id": int(f.id), "file_name": f.original_name,
                         "path": "", "kind": "unknown"})
            known.add(int(f.id))
        rows = rows[:10]
    if not rows:
        return ("Не удалось определить, о каких файлах речь. Назовите файл "
                "(например, «покажи путь к договору по Вилоновской») или "
                "обратитесь к файлам из предыдущего ответа по имени.", [])
    lines = ["Пути файлов на диске:"]
    chips: list[dict] = []
    for r in rows:
        if r["path"]:
            p = Path(r["path"])
            lines.append(f"- {r['file_name']} (file_id:{r['file_id']}): {p}")
            lines.append(f"  ссылка: file:///{str(p).replace(chr(92), '/')}")
        else:
            lines.append(f"- {r['file_name']} (file_id:{r['file_id']}): путь на диске не запомнен "
                         "(файл загружен через браузер; копия лежит в картотеке агента)")
        chips.append({"file_id": r["file_id"], "file_name": r["file_name"],
                      "doc_type": "other"})
    return "\n".join(lines), chips


# ---------- обработка планов планировщика (LLM-first) ----------

def run_plan_action(question: str, action: str, plan: dict, db: Session,
                    actor: str | None) -> dict | None:
    """file_link/file_move/file_copy/file_mkdir из плана планировщика.

    None — действие не относится к файловым (для цепочки _run_plan).
    Проверки прав: files_view (пути), files_manage (операции).
    """
    if action not in ("file_link", "file_move", "file_copy", "file_mkdir"):
        return None
    from doc_agent.services.intents import intent_result

    username = actor or ""
    if action == "file_link":
        if not users_store.has_permission(username, "files_view"):
            return intent_result(
                "Показ путей к файлам на диске разрешён не всем пользователям "
                "(право files_view). Обратитесь к администратору.", [], "file_link", question)
        terms = plan.get("terms") or []
        file_ids = plan.get("file_ids") or []
        text, chips = file_link_block(terms, file_ids, db)
        return intent_result(text, chips, "file_link", question)

    # операции требуют files_manage
    if not users_store.has_permission(username, "files_manage"):
        return intent_result(
            "Операции с файлами на диске (перемещение/копирование/создание "
            "папок) разрешены не всем пользователям (право files_manage) или "
            "не настроены разрешённые корни. Обратитесь к администратору.",
            [], action, question)
    dest = str(plan.get("path") or "").strip()
    file_ids = plan.get("file_ids") or []
    create_dest = bool(plan.get("create_dest", True))
    try:
        if action == "file_mkdir":
            target = make_dir(dest, username)
            return intent_result(
                f"Папка создана: {target}", [], action, question)
        if not file_ids:
            return intent_result(
                "Не указано, какой файл обработать: назовите документ из "
                "картотеки (например, «перемести договор по Вилоновской "
                "в папку D:/Отчёты»).", [], action, question)
        results = []
        for fid in file_ids[:5]:
            if action == "file_move":
                results.append(move_file(int(fid), dest, username, create_dest))
            else:
                results.append(copy_file(int(fid), dest, username, create_dest))
        verb = "Перемещено" if action == "file_move" else "Скопировано"
        lines = [f"{verb} файлов: {len(results)}"]
        for r in results:
            lines.append(f"- {r['from']} -> {r['to']}")
        if any(r.get("exported_from_agent") or r.get("copied_from_agent") for r in results):
            lines.append("(исходник взят из хранилища агента: запомненный путь "
                         "отсутствует — файл загружен через браузер)")
        return intent_result("\n".join(lines), [
            {"file_id": r["file_id"], "file_name": Path(r["to"]).name, "doc_type": "other"}
            for r in results
        ], action, question)
    except FileOpsError as exc:
        return intent_result(
            f"Файловая операция не выполнена: {exc}\n"
            f"Разрешённые корни: {roots_summary(username)}", [], action, question)

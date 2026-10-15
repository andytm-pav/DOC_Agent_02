"""Watchdog: слежение за папками входящих (config: watchdog.enabled/paths).

v3.0.3 — РЕКОНСИЛИАЦИЯ: раньше отслеживались только НОВЫЕ файлы
(on_created), а удаление/перемещение/изменение файла на диске оставляло
картотеку и память путей устаревшими — агент давал мёртвые ссылки
(file_link по несуществующему пути) и отвечал по старому содержимому.
Теперь:

  - новые файлы по-прежнему импортируются (enqueue_file), их путь
    запоминается (fileops.remember) — watcher-файлы больше не «без адреса»
    (раньше путь запоминался только при импорте папки);
  - перемещение/переименование (on_moved) — путь пере-привязывается,
    переиндексация не нужна (дедуп по sha256 вернёт ту же карточку);
  - изменение содержимого (on_modified + сверка размера/mtime/sha256) —
    пере-приём файла (watchdog.on_modify: reingest, по умолчанию) или
    игнор; изменившийся sha создаёт новую карточку, старая (с прежним
    sha по этому пути) удаляется с записью в audit_log;
  - удаление (on_deleted) — по watchdog.on_delete:
      forget_path (по умолчанию) — путь помечается устаревшим
      (is_current=0), карточка с содержимым ОСТАЁТСЯ (копия в
      data/storage не зависит от судьбы оригинала; сценарий «папка-след»,
      откуда файлы забирают, ничего не теряет);
      remove — карточка удаляется целиком (services.ingest.remove_file);
  - догоняющая сверка (polling-режим): актуальные пути карточек внутри
    watched-папок, которых нет на диске (событие пропущено/агент был
    выключен), обрабатываются той же политикой on_delete.

track_changes: false возвращает поведение v3.0.2 (только новые файлы).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from doc_agent.config import load_settings
from doc_agent.logging import get_logger
from doc_agent.services import fileops
from doc_agent.services.ingest import enqueue_file, remove_file

log = get_logger("services.watcher")

_observer = None
_stop_event = threading.Event()
# v3.0.3: путь -> (size, mtime_ns); раньше был set[str] — «новый» файл
# нельзя было отличить от «изменившегося»
_seen: dict[str, tuple[int, int]] = {}


def _watched_dirs(settings) -> list[Path]:  # noqa: ANN001 — Settings не экспортируется
    out: list[Path] = []
    for raw_path in settings.watchdog.paths:
        p = Path(raw_path)
        if not p.is_absolute():
            p = settings.app.data_path.parent / p
        out.append(p)
    return out


def _is_under(path: Path, root: Path) -> bool:
    """path совпадает с root или лежит внутри него (оба resolved)."""
    try:
        rp = path.resolve()
        rr = root.resolve()
    except OSError:  # noqa: PERF203
        return False
    return rp == rr or rr in rp.parents


def _stat_sig(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


# ------------------- приём/удаление карточек -------------------


def _remember_ingested(path: Path, result: dict) -> None:
    """v3.0.3: путь запоминается и для watcher-приёма — раньше watcher-файлы
    не попадали в file_locations (file_link/перемещение для них не работали,
    а реконсилиация не могла связать диск с карточкой). Повторный приём
    дубликата (перезапуск агента) путь НЕ перезаписывает."""
    fid = result.get("file_id")
    if not fid:
        return
    try:
        p = str(path.resolve())
        if any(loc["path"] == p and loc["is_current"]
               for loc in fileops.locations_for(int(fid))):
            return
        fileops.remember(int(fid), p, kind="original")
    except Exception as exc:  # noqa: BLE001 — память путей не ломает приём
        log.warning("watcher_remember_failed", file=path.name, error=str(exc))


def _ingest_new(path: Path) -> None:
    try:
        result = enqueue_file(path, path.name, source="watcher")
        _remember_ingested(path, result)
        log.info("watcher_ingested", file=path.name, result=result)
    except Exception as exc:  # noqa: BLE001
        log.warning("watcher_failed", file=path.name, error=str(exc))


def _handle_gone(path: Path, actor: str = "watcher") -> None:
    """Файл исчез из watched-папки: политика watchdog.on_delete."""
    # сверка путей — в ЕДИНОМ представлении (remember хранит resolve();
    # события/итерация могут приходить с «./» и регистром в другой записи)
    try:
        path = path.resolve()
    except OSError:
        pass
    settings = load_settings()
    if settings.watchdog.on_delete == "remove":
        for fid in fileops.file_ids_at(str(path)):
            try:
                remove_file(fid, f"файл удалён с диска: {path}", actor=actor)
            except Exception as exc:  # noqa: BLE001
                log.warning("watcher_remove_failed", file=str(path), error=str(exc))
    fileops.forget_path(str(path), actor=actor)


def _handle_modified(path: Path) -> None:
    """Содержимое изменилось (размер/mtime) — сверяем sha256 и пере-принимаем.

    Дедуп по sha делает повтор безопасным: неизменённый файл вернёт
    «Дубликат» и ничего не задвоит; изменившийся sha создаёт новую
    карточку, а карточки со старым sha по этому пути удаляются."""
    if load_settings().watchdog.on_modify != "reingest":
        return
    try:
        path = path.resolve()
    except OSError:
        pass
    import hashlib

    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        disk_sha = h.hexdigest()
    except OSError as exc:
        log.warning("watcher_hash_failed", file=path.name, error=str(exc))
        return
    from doc_agent.db.models import File
    from doc_agent.db.session import get_session_factory

    stale: list[int] = []
    factory = get_session_factory()
    with factory() as db:
        for fid in fileops.file_ids_at(str(path), db=db):
            f = db.get(File, fid)
            if f is not None and f.sha256 != disk_sha:
                stale.append(fid)
    if not stale and fileops.file_ids_at(str(path)):
        return  # содержимое не менялось — событие-шум
    for fid in stale:
        try:
            remove_file(fid, f"файл изменён на диске: {path}")
        except Exception as exc:  # noqa: BLE001
            log.warning("watcher_remove_failed", file=path.name, error=str(exc))
    _ingest_new(path)


def _handle_moved(src: Path, dst: Path) -> None:
    """Перемещение/переименование: путь пере-привязывается БЕЗ политики
    удаления (содержимое сохранилось — карточку нельзя терять)."""
    fileops.forget_path(str(src))
    if dst.exists():
        _ingest_new(dst)  # дедуп по sha вернёт существующую карточку


# ------------------- циклы -------------------


def _scan_once() -> None:
    """Один проход polling-цикла: новые/изменившиеся/исчезнувшие файлы."""
    settings = load_settings()
    seen_now: set[str] = set()
    for p in _watched_dirs(settings):
        if not p.exists():
            continue
        try:
            entries = sorted(p.iterdir())
        except OSError as exc:
            log.warning("watcher_scan_failed", path=str(p), error=str(exc))
            continue
        for f in entries:
            if not f.is_file():
                continue
            key = str(f)
            seen_now.add(key)
            sig = _stat_sig(f)
            if key not in _seen:
                _seen[key] = sig or (0, 0)
                _ingest_new(f)
            elif sig is not None and sig != _seen[key]:
                # изменились размер/mtime — ждём окончания записи
                for _ in range(5):
                    time.sleep(0.5)
                    nxt = _stat_sig(f)
                    if nxt is None:
                        break
                    if nxt == sig:
                        break
                    sig = nxt
                if sig is not None:
                    _seen[key] = sig
                if f.exists():
                    _handle_modified(f)
    for key in [k for k in _seen if k not in seen_now]:
        _seen.pop(key, None)
        if load_settings().watchdog.track_changes:
            _handle_gone(Path(key))
    if settings.watchdog.track_changes:
        _reconcile(settings)


def _reconcile(settings) -> None:  # noqa: ANN001
    """Догоняющая сверка: актуальные пути карточек внутри watched-папок,
    которых нет на диске (событие пропущено / агент был выключен)."""
    from sqlalchemy import select

    from doc_agent.db.models import FileLocation
    from doc_agent.db.session import get_session_factory

    roots = _watched_dirs(settings)
    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(
            select(FileLocation.path).where(FileLocation.is_current == 1)
        ).scalars().all()
    for loc in rows:
        p = Path(loc)
        if p.exists() or not p.is_absolute():
            continue
        if not any(_is_under(p, root) for root in roots):
            continue  # вне watched-папок реконсилиация не решает судьбу карточек
        _handle_gone(p)


def _scan_loop() -> None:
    settings = load_settings()
    interval = max(settings.watchdog.interval_sec, 1)
    while not _stop_event.is_set():
        try:
            _scan_once()
        except Exception as exc:  # noqa: BLE001 — цикл не должен умирать
            log.warning("watcher_cycle_failed", error=str(exc))
        _stop_event.wait(interval)


def _watchdog_loop_with_events() -> None:
    """watchdog Observer поверх polling-фоллбэка."""
    global _observer
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class Handler(FileSystemEventHandler):
            def on_created(self, event) -> None:  # type: ignore[no-untyped-def]
                if event.is_directory:
                    return
                path = Path(str(event.src_path))
                for _ in range(5):  # ждём окончания записи
                    if path.exists() and path.stat().st_size > 0:
                        break
                    time.sleep(0.5)
                sig = _stat_sig(path)
                if sig is not None:
                    _seen[str(path)] = sig
                _ingest_new(path)

            # --- v3.0.3: реконсилиация (удаление/перемещение/изменение) ---
            def on_deleted(self, event) -> None:  # type: ignore[no-untyped-def]
                if event.is_directory:
                    return
                path = Path(str(event.src_path))
                _seen.pop(str(path), None)
                if load_settings().watchdog.track_changes:
                    _handle_gone(path)

            def on_moved(self, event) -> None:  # type: ignore[no-untyped-def]
                if event.is_directory:
                    return
                src, dst = Path(str(event.src_path)), Path(str(event.dest_path))
                _seen.pop(str(src), None)
                sig = _stat_sig(dst)
                if sig is not None:
                    _seen[str(dst)] = sig
                if load_settings().watchdog.track_changes:
                    _handle_moved(src, dst)

            def on_modified(self, event) -> None:  # type: ignore[no-untyped-def]
                if event.is_directory:
                    return
                path = Path(str(event.src_path))
                if not path.exists():
                    return
                sig = _stat_sig(path)
                if sig is None or _seen.get(str(path)) == sig:
                    return  # шум/повтор после собственной записи
                _seen[str(path)] = sig
                if load_settings().watchdog.track_changes:
                    _handle_modified(path)

        _observer = Observer()
        settings = load_settings()
        for p in _watched_dirs(settings):
            if p.exists():
                _observer.schedule(Handler(), str(p), recursive=False)
        _observer.start()
        _observer.join()
        return
    except Exception as exc:  # noqa: BLE001
        log.warning("watchdog_observer_unavailable", error=str(exc))
    _scan_loop()


def start_watcher() -> None:
    global _observer
    settings = load_settings()
    if not settings.watchdog.enabled:
        return
    _stop_event.clear()
    t = threading.Thread(target=_watchdog_loop_with_events, name="watcher", daemon=True)
    t.start()
    log.info("watcher_started", paths=settings.watchdog.paths,
             track_changes=settings.watchdog.track_changes)


def stop_watcher() -> None:
    global _observer
    _stop_event.set()
    if _observer is not None:
        try:
            _observer.stop()
        except Exception:  # noqa: BLE001
            pass
        _observer = None

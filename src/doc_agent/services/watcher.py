"""Watchdog: слежение за папками входящих (config: watchdog.enabled/paths)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from doc_agent.config import load_settings
from doc_agent.logging import get_logger
from doc_agent.services.ingest import enqueue_file

log = get_logger("services.watcher")

_observer = None
_stop_event = threading.Event()
_seen: set[str] = set()


def _scan_loop() -> None:
    settings = load_settings()
    interval = settings.watchdog.interval_sec
    while not _stop_event.is_set():
        for raw_path in settings.watchdog.paths:
            p = Path(raw_path)
            if not p.is_absolute():
                p = settings.app.data_path.parent / p
            if not p.exists():
                continue
            for f in sorted(p.iterdir()):
                if f.is_file() and str(f) not in _seen:
                    _seen.add(str(f))
                    try:
                        result = enqueue_file(f, f.name, source="watcher")
                        log.info("watcher_ingested", file=f.name, result=result)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("watcher_failed", file=f.name, error=str(exc))
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
                try:
                    enqueue_file(path, path.name, source="watcher")
                    log.info("watcher_ingested", file=path.name)
                except Exception as exc:  # noqa: BLE001
                    log.warning("watcher_failed", file=path.name, error=str(exc))

        _observer = Observer()
        settings = load_settings()
        for raw_path in settings.watchdog.paths:
            p = Path(raw_path)
            if not p.is_absolute():
                p = settings.app.data_path.parent / p
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
    log.info("watcher_started", paths=settings.watchdog.paths)


def stop_watcher() -> None:
    global _observer
    _stop_event.set()
    if _observer is not None:
        try:
            _observer.stop()
        except Exception:  # noqa: BLE001
            pass
        _observer = None

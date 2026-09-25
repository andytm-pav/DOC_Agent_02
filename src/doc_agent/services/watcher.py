"""File watcher service using watchdog."""

import time
from pathlib import Path

import structlog
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from doc_agent.config import get_settings
from doc_agent.services.ingest import ingest_file

logger = structlog.get_logger()


class InboxHandler(FileSystemEventHandler):
    """Handle new files in watched directories."""

    def on_created(self, event: object) -> None:
        if not event.is_directory:
            file_path = str(event.src_path)
            name = Path(file_path).name
            logger.info("New file detected", path=file_path)
            try:
                result = ingest_file(file_path, name, source="watcher")
                logger.info("Watched file ingested", result=result)
            except Exception as e:
                logger.error("Failed to ingest watched file", error=str(e))


def start_watcher() -> None:
    """Start the file watcher."""
    settings = get_settings()

    if not hasattr(settings, "watchdog_enabled") or not settings.watchdog_enabled:
        logger.info("Watchdog disabled")
        return

    observer = Observer()
    for watch_path in ["./data/inbox"]:
        path = Path(watch_path)
        path.mkdir(parents=True, exist_ok=True)
        observer.schedule(InboxHandler(), str(path), recursive=False)
        logger.info("Watching directory", path=str(path))

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

"""structlog: JSON-логи в stdout + файл data/logs/app.log (для /admin/logs)."""
from __future__ import annotations

import logging
import logging.handlers
from typing import Any

import structlog

from doc_agent.config import load_settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    settings = load_settings()
    log_dir = settings.app.sub_dir("logs")
    log_file = log_dir / "app.log"

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(), file_handler], force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _configured = True


def get_logger(name: str) -> Any:
    setup_logging()
    return structlog.get_logger(name)

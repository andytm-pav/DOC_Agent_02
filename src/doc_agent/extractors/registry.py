"""Реестр экстракторов: авторегистрация + автозагрузка пользовательских плагинов из plugins/."""
from __future__ import annotations

import importlib.util
import sys
from typing import Callable

from doc_agent.config import REPO_ROOT
from doc_agent.extractors.base import ExtractorFunc, ExtractResult
from doc_agent.logging import get_logger

log = get_logger("extractors.registry")

_registry: dict[str, ExtractorFunc] = {}


def register(*formats: str) -> Callable[[ExtractorFunc], ExtractorFunc]:
    def deco(fn: ExtractorFunc) -> ExtractorFunc:
        for fmt in formats:
            _registry[fmt] = fn
        return fn
    return deco


def get_extractor(fmt: str) -> ExtractorFunc | None:
    _load_plugins()
    return _registry.get(fmt)


def known_formats() -> list[str]:
    return sorted(_registry)


def _load_plugins() -> None:
    """Плагины пользователя: plugins/*.py вызывают register("ext")(fn)."""
    if getattr(_load_plugins, "_done", False):
        return
    _load_plugins._done = True  # type: ignore[attr-defined]
    plugins_dir = REPO_ROOT / "plugins"
    for py in sorted(plugins_dir.glob("*.py")):
        mod_name = f"doc_agent_plugin_{py.stem}"
        if mod_name in sys.modules:
            continue
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
                log.info("plugin_loaded", plugin=py.name)
        except Exception as exc:  # noqa: BLE001
            log.warning("plugin_failed", plugin=py.name, error=str(exc))


__all__ = ["register", "get_extractor", "known_formats", "ExtractResult"]

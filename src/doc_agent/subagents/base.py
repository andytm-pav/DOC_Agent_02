"""Интерфейс субагента (раздел 7 ТЗ)."""
from __future__ import annotations

from typing import Any, Protocol


class Subagent(Protocol):
    name: str

    def run(self, **kwargs: Any) -> Any: ...

"""Base subagent interface."""

from typing import Any, Protocol


class Subagent(Protocol):
    """Protocol for all subagents."""

    async def run(self, **kwargs: Any) -> Any:
        """Execute the subagent task."""
        ...

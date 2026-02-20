"""LLM client abstraction for rtw.

Default backend: Cursor Agent CLI (see cursor.py).
"""

from abc import ABC, abstractmethod
from typing import Any


class LLMResponseError(RuntimeError):
    """Raised when the LLM returns empty or unparseable output."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


class LLMClient(ABC):
    """Abstract base for LLM backends."""

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """Generate a completion for the given prompt."""
        pass

    @abstractmethod
    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        """Generate a JSON-structured completion."""
        pass

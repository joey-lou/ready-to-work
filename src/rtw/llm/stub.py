"""Stub LLM client for testing and mock mode."""

import json
from typing import Any

from rtw.llm.client import LLMClient, LLMResponseError


class StubLLMClient(LLMClient):
    """
    Minimal stub client for CLI --mock mode.

    Matches prompts/system text against response keys (case-insensitive substring)
    and returns the associated string. No call tracking or error injection.
    """

    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {}

    def _find_response(self, prompt: str, system: str | None) -> str:
        for text in [(system or ""), prompt]:
            for key, value in self.responses.items():
                if key.lower() in text.lower():
                    return value
        return "Stub response"

    def complete(self, prompt: str, system: str | None = None) -> str:
        return self._find_response(prompt, system)

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        raw = self._find_response(prompt, system)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMResponseError("Stub client: invalid JSON in responses dict", raw=raw) from e

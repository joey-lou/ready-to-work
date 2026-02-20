"""MockLLMClient: full-featured test double for the LLM layer."""

import json
from typing import Any

from rtw.llm import LLMClient


class MockLLMClient(LLMClient):
    """
    Mock client for testing the flow without LLM calls.

    Supports:
    - Key-based response routing (matched against system prompt then user prompt)
    - Per-call and per-key call tracking
    - Error injection on a specific call number (fail_on_call)
    - Malformed JSON injection for complete_json (fail_with_json_error)
    - side_effect callable for custom behavior
    - response_sequence: dict[str, list[str]] for ordered per-key responses
      (cycles on last entry when exhausted)
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        fail_on_call: int | None = None,
        fail_with_json_error: bool = False,
        side_effect: Any | None = None,
        response_sequence: dict[str, list[str]] | None = None,
    ):
        self.responses = responses or {}
        self.response_sequence = response_sequence or {}
        self._sequence_indices: dict[str, int] = {}
        self.call_count = 0
        self.call_counts: dict[str, int] = {}
        self.fail_on_call = fail_on_call
        self.fail_with_json_error = fail_with_json_error
        self.side_effect = side_effect

    def _find_response(self, prompt: str, system: str | None) -> str:
        """Locate matching response key and track per-key call count."""
        matched_key = None

        search_targets = [(system or ""), prompt]
        for text in search_targets:
            if matched_key:
                break
            for key in {**self.response_sequence, **self.responses}:
                if key.lower() in text.lower():
                    matched_key = key
                    break

        if matched_key is not None:
            self.call_counts[matched_key] = self.call_counts.get(matched_key, 0) + 1

            if matched_key in self.response_sequence:
                seq = self.response_sequence[matched_key]
                idx = self._sequence_indices.get(matched_key, 0)
                response = seq[min(idx, len(seq) - 1)]
                self._sequence_indices[matched_key] = idx + 1
                return response

            return self.responses[matched_key]

        return f"Mock response #{self.call_count}"

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.call_count += 1

        if self.fail_on_call is not None and self.call_count == self.fail_on_call:
            raise RuntimeError(f"Injected failure on call #{self.call_count}")

        if self.side_effect is not None:
            return self.side_effect(prompt, system)

        return self._find_response(prompt, system)

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        if self.fail_with_json_error:
            self.call_count += 1
            if self.fail_on_call is not None and self.call_count == self.fail_on_call:
                raise RuntimeError(f"Injected failure on call #{self.call_count}")
            raise RuntimeError("Injected JSON error: not valid json {{{")

        response = self.complete(prompt, system)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"mock": True, "response": response}

"""Shared test helpers: constants and factory functions for rtw test suite."""

import json
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, StepResult, StepStatus
from rtw.cli import create_flow
from rtw.core import Flow, SharedState

PLAN_RESPONSE = '{"summary": "Plan", "steps": [{"id": 1, "description": "Do it", "type": "create", "target": "f.py", "details": "details"}]}'
APPROVE_RESPONSE = '{"verdict": "approve", "score": 90, "summary": "Good", "assessment": "Everything looks good.", "blocking_reason": null}'
ITERATE_RESPONSE = '{"verdict": "iterate", "score": 50, "summary": "Needs work", "assessment": "The implementation needs more work. Fix it.", "blocking_reason": null}'
BLOCKED_RESPONSE = '{"verdict": "blocked", "score": 0, "summary": "Stuck", "assessment": "Cannot proceed.", "blocking_reason": "Cannot proceed"}'


class MockAgentBackend(AgentBackend):
    """
    Configurable mock agent backend for testing.

    Implements AgentBackend with key-based response routing, error injection,
    side_effect, and response_sequence (same behavior as previous MockLLMClient).
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

    @property
    def name(self) -> str:
        return "mock"

    def _find_response(self, prompt: str, system: str | None) -> str:
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
        return f'{{"mock": true, "call": {self.call_count}}}'

    def execute_step(
        self,
        step: dict[str, Any],
        workspace: Path,
        context: dict[str, Any] | None = None,
    ) -> StepResult:
        return StepResult(
            step_id=step.get("id", 0),
            status=StepStatus.COMPLETED,
            description=step.get("description", ""),
            action_taken="Mock action",
            files_changed=[],
        )

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        self.call_count += 1
        if self.fail_on_call is not None and self.call_count == self.fail_on_call:
            raise RuntimeError(f"Injected failure on call #{self.call_count}")
        if self.fail_with_json_error:
            raise RuntimeError("Injected JSON error: not valid json {{{")
        if self.side_effect is not None:
            out = self.side_effect(prompt, system)
            if isinstance(out, dict):
                return out
            return json.loads(out) if isinstance(out, str) else {"mock": out}
        raw = self._find_response(prompt, system)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"mock": True, "response": raw}


def make_architect_flow(agent: AgentBackend, on_state_change=None) -> Flow:
    return create_flow(agent, on_state_change=on_state_change)


def make_state(**kwargs: Any) -> SharedState:
    defaults = {"task_file": "task.md", "task_content": "Do something", "workspace": "/tmp"}
    defaults.update(kwargs)
    return SharedState(**defaults)

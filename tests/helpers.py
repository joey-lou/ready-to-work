"""Shared test helpers: constants and factory functions for rtw test suite."""

from typing import Any

from llm_mock import MockLLMClient

from rtw.agent import AgentBackend, StepResult, StepStatus
from rtw.cli import create_flow
from rtw.core import Flow, SharedState

PLAN_RESPONSE = '{"summary": "Plan", "steps": [{"id": 1, "description": "Do it", "type": "create", "target": "f.py", "details": "details"}]}'
APPROVE_RESPONSE = '{"verdict": "approve", "score": 90, "summary": "Good", "assessment": "Everything looks good.", "blocking_reason": null}'
ITERATE_RESPONSE = '{"verdict": "iterate", "score": 50, "summary": "Needs work", "assessment": "The implementation needs more work. Fix it.", "blocking_reason": null}'
BLOCKED_RESPONSE = '{"verdict": "blocked", "score": 0, "summary": "Stuck", "assessment": "Cannot proceed.", "blocking_reason": "Cannot proceed"}'


class MockAgentBackend(AgentBackend):
    """Mock agent backend for testing - no subprocess infrastructure needed."""

    def __init__(self, llm_client: MockLLMClient):
        self.llm_client = llm_client

    @property
    def name(self) -> str:
        return "mock"

    def execute_step(self, step, workspace, context=None) -> StepResult:
        return StepResult(
            step_id=step.get("id", 0),
            status=StepStatus.COMPLETED,
            description=step.get("description", ""),
            action_taken="Mock action",
            files_changed=[],
        )

    def complete_json(self, prompt, system=None) -> dict[str, Any]:
        return self.llm_client.complete_json(prompt, system)


def make_mock_llm(verdict_response: str = APPROVE_RESPONSE) -> MockLLMClient:
    return MockLLMClient(
        responses={
            "architect": PLAN_RESPONSE,
            "reviewer": verdict_response,
        }
    )


def make_mock_agent(llm: MockLLMClient) -> MockAgentBackend:
    return MockAgentBackend(llm)


def make_architect_flow(agent: AgentBackend, on_state_change=None) -> Flow:
    return create_flow(agent, on_state_change=on_state_change)


def make_state(**kwargs) -> SharedState:
    defaults = {"task_file": "task.md", "task_content": "Do something", "workspace": "/tmp"}
    defaults.update(kwargs)
    return SharedState(**defaults)

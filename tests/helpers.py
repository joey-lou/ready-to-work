"""Shared test helpers: constants and factory functions for rtw test suite."""

from pathlib import Path
from typing import Any

from llm_mock import MockLLMClient

from rtw.agent import AgentBackend, StepResult, StepStatus
from rtw.architect import ExecutorNode, PlannerNode, ReviewerNode
from rtw.core import Flow, SharedState

PLAN_RESPONSE = '{"summary": "Plan", "steps": [{"id": 1, "description": "Do it", "type": "create", "target": "f.py", "details": "details"}], "dependencies": [], "risks": [], "estimated_complexity": "low"}'
APPROVE_RESPONSE = '{"verdict": "approve", "score": 90, "summary": "Good", "strengths": [], "issues": [], "feedback": "", "blocking_reason": null}'
ITERATE_RESPONSE = '{"verdict": "iterate", "score": 50, "summary": "Needs work", "strengths": [], "issues": [], "feedback": "Fix it", "blocking_reason": null}'
BLOCKED_RESPONSE = '{"verdict": "blocked", "score": 0, "summary": "Stuck", "strengths": [], "issues": [], "feedback": "", "blocking_reason": "Cannot proceed"}'


class MockAgentBackend(AgentBackend):
    """Mock agent backend for testing - bypasses subprocess infrastructure."""

    def __init__(self, llm_client: MockLLMClient):
        # Don't call super().__init__ - we don't need workspace/model/timeout
        self.llm_client = llm_client
        self.workspace = Path("/tmp")
        self.model = None
        self.timeout = 60

    @property
    def name(self) -> str:
        return "mock"

    # Override the high-level methods directly (skip the subprocess layer)
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

    # Implement abstract methods (not used since we override execute_step/complete_json)
    def _build_exec_command(self, prompt: str, workspace: Path) -> list[str]:
        return ["echo", "mock"]

    def _build_json_command(self, prompt: str) -> list[str]:
        return ["echo", "{}"]

    def _parse_exec_output(self, output: str, step_id: int, description: str) -> StepResult:
        return StepResult(step_id=step_id, status=StepStatus.COMPLETED, description=description)

    def _parse_json_output(self, output: str) -> dict[str, Any]:
        return {}


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
    planner = PlannerNode(agent)
    executor = ExecutorNode(agent)
    reviewer = ReviewerNode(agent)

    planner.on("build") >> executor
    executor.on("review") >> reviewer
    reviewer.on("plan") >> planner

    return Flow(start=planner, name="architect", on_state_change=on_state_change)


def make_state(**kwargs) -> SharedState:
    defaults = {"task_file": "task.md", "task_content": "Do something", "workspace": "/tmp"}
    defaults.update(kwargs)
    return SharedState(**defaults)

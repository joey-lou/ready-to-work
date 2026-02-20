"""Shared test helpers: constants and factory functions for rtw test suite."""

from llm_mock import MockLLMClient

from rtw.architect import BuilderNode, PlannerNode, ReviewerNode
from rtw.core import Flow, SharedState

PLAN_RESPONSE = '{"summary": "Plan", "steps": [{"id": 1, "description": "Do it", "type": "create", "target": "f.py", "details": "details"}], "dependencies": [], "risks": [], "estimated_complexity": "low"}'
BUILD_RESPONSE = '{"completed_steps": [{"step_id": 1, "status": "completed", "action_taken": "Done", "files_affected": ["f.py"], "notes": ""}], "artifacts_created": [{"path": "f.py", "action": "created"}], "issues_encountered": [], "next_steps_suggested": []}'
APPROVE_RESPONSE = '{"verdict": "approve", "score": 90, "summary": "Good", "strengths": [], "issues": [], "feedback": "", "blocking_reason": null}'
ITERATE_RESPONSE = '{"verdict": "iterate", "score": 50, "summary": "Needs work", "strengths": [], "issues": [], "feedback": "Fix it", "blocking_reason": null}'
BLOCKED_RESPONSE = '{"verdict": "blocked", "score": 0, "summary": "Stuck", "strengths": [], "issues": [], "feedback": "", "blocking_reason": "Cannot proceed"}'


def make_mock_llm(verdict_response: str = APPROVE_RESPONSE) -> MockLLMClient:
    return MockLLMClient(
        responses={
            "architect": PLAN_RESPONSE,
            "developer": BUILD_RESPONSE,
            "reviewer": verdict_response,
        }
    )


def make_architect_flow(llm, on_state_change=None) -> Flow:
    planner = PlannerNode(llm)
    builder = BuilderNode(llm)
    reviewer = ReviewerNode(llm)

    planner.on("build") >> builder
    builder.on("review") >> reviewer
    reviewer.on("plan") >> planner

    return Flow(start=planner, name="architect", on_state_change=on_state_change)


def make_state(**kwargs) -> SharedState:
    defaults = {"task_file": "task.md", "task_content": "Do something", "workspace": "/tmp"}
    defaults.update(kwargs)
    return SharedState(**defaults)

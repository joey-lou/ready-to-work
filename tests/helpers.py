"""Shared test helpers: constants and factory functions for rtw test suite."""

import json
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentResult
from rtw.cli import create_flow
from rtw.core import Flow, SharedState

_VALID_PLAN = """# Plan

## Steps
1. One step

## Lessons

"""

_VALID_SUBTASK = """# Subtask

## Acceptance criteria
- [ ] criterion

"""

_VALID_SUBTASK_REVIEWED = """# Subtask

## Acceptance criteria
- [x] criterion

## Review
Passed.

"""


class MockAgentBackend(AgentBackend):
    """Mock backend for tests. Writes state.json/PLAN/SUBTASK based on prompt (Planner/Reviewer)."""

    def __init__(
        self,
        plan_status: str = "COMPLETED",
        side_effect: Any = None,
    ):
        self.plan_status = plan_status
        self.side_effect = side_effect

    @property
    def name(self) -> str:
        return "mock"

    def execute(
        self,
        workspace: Path,
        prompt: str,
        run_dir: Path | None = None,
    ) -> AgentResult:
        if self.side_effect is not None and callable(self.side_effect):
            self.side_effect(workspace, prompt, run_dir)
        target = run_dir or workspace
        state_file = Path(target) / "state.json"
        if "Planner" in prompt:
            target = Path(target)
            target.mkdir(parents=True, exist_ok=True)
            data = json.loads(state_file.read_text()) if state_file.exists() else {}
            data["plan_status"] = self.plan_status
            data["blocking_reason"] = None
            state_file.write_text(json.dumps(data, indent=2))
            (target / "PLAN.md").write_text(_VALID_PLAN)
            (target / "SUBTASK.md").write_text(_VALID_SUBTASK)
        if "Reviewer" in prompt and run_dir:
            target = Path(run_dir)
            target.mkdir(parents=True, exist_ok=True)
            data = json.loads(state_file.read_text()) if state_file.exists() else {}
            data["subtask_status"] = "PASSED"
            data["blocking_reason"] = None
            state_file.write_text(json.dumps(data, indent=2))
            (target / "SUBTASK.md").write_text(_VALID_SUBTASK_REVIEWED)
        return AgentResult(success=True, output="Done.")


def make_architect_flow(agent: AgentBackend, on_state_change=None) -> Flow:
    return create_flow(agent, on_state_change=on_state_change)


def make_state(**kwargs: Any) -> SharedState:
    defaults = {
        "task_file": "/tmp/task.md",
        "task_content": "Do something",
        "workspace": "/tmp",
        "run_dir": "/tmp/.rtw/runs/test",
    }
    defaults.update(kwargs)
    return SharedState(**defaults)

"""Flow: run loop, action routing, max iterations, persistence callback."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from helpers import MockAgentBackend, make_architect_flow, make_state

from rtw.architect.executor import ExecutorNode
from rtw.core import Flow, FlowStatus, Node, SharedState


class CounterNode(Node):
    """Node that loops until count reaches max (Flow increments iteration per visit)."""

    def __init__(self, name: str, max_count: int = 3):
        super().__init__(name)
        self.max_count = max_count
        self.increments_iteration = True

    def exec(self, prep_result):
        return None

    def post(self, state: SharedState, prep_result, exec_result) -> str | None:
        if state.current_iteration >= self.max_count:
            return None
        return "next"

    def prep(self, state: SharedState):
        return None


def test_flow_runs_until_node_returns_none():
    """Flow runs until post() returns None."""
    node = CounterNode("counter", max_count=3)
    node.on("next") >> node
    flow = Flow(start=node)
    state = SharedState(workspace="/tmp", run_dir="/tmp/.rtw/runs/test")
    result = flow.run(state)
    assert result.current_iteration == 3


def test_executor_runs_when_current_iteration_equals_max_iterations():
    """Regression (#16): executor runs after the Nth planning round when max_iterations=N."""

    class RecordingPlanner(Node):
        def __init__(self) -> None:
            super().__init__("RecPlan")
            self.increments_iteration = True
            self.count = 0

        def exec(self, prep_result):
            return None

        def post(self, state: SharedState, prep_result, exec_result) -> str | None:
            self.count += 1
            if state.current_iteration >= 2:
                return "go_exec"
            return "loop"

    class RecordingExec(Node):
        def __init__(self) -> None:
            super().__init__("RecExec")
            self.ran = False

        def exec(self, prep_result):
            return None

        def post(self, state: SharedState, prep_result, exec_result) -> str | None:
            self.ran = True
            return None

    pl = RecordingPlanner()
    pl.on("loop") >> pl
    ex = RecordingExec()
    pl.on("go_exec") >> ex
    state = SharedState(workspace="/tmp", run_dir="/tmp/.rtw/runs/t", max_iterations=2)
    Flow(start=pl).run(state)
    assert pl.count == 2
    assert ex.ran


def test_flow_stops_at_max_iterations_and_sets_blocked():
    """When current_iteration would exceed max_iterations, flow stops and sets BLOCKED."""
    node = CounterNode("counter", max_count=100)
    node.on("next") >> node
    flow = Flow(start=node)
    state = SharedState(workspace="/tmp", run_dir="/tmp/.rtw/runs/test", max_iterations=5)
    result = flow.run(state)
    assert result.current_iteration <= 5
    assert result.status == FlowStatus.BLOCKED
    assert "planning rounds" in (result.blocking_reason or "").lower()


def test_flow_routes_by_action_string():
    """Flow routes to successor for action string returned by post()."""
    a = CounterNode("A", max_count=2)  # first run returns "next"
    b = CounterNode("B", max_count=2)  # second run returns None
    a.on("next") >> b
    b.on("next") >> a
    flow = Flow(start=a)
    state = SharedState(workspace="/tmp", run_dir="/tmp/.rtw/runs/test")
    flow.run(state)
    # A runs (iteration 1), returns "next" -> B runs (iteration 2), returns None
    assert state.current_iteration == 2


def test_flow_calls_on_state_change_after_each_node():
    """When on_state_change is set, it is called after each node run."""
    node = CounterNode("counter", max_count=2)
    node.on("next") >> node
    calls = []
    flow = Flow(start=node, on_state_change=lambda s: calls.append(s.current_iteration))
    state = SharedState(workspace="/tmp", run_dir="/tmp/.rtw/runs/test")
    flow.run(state)
    assert calls == [1, 2]


def test_executor_failure_blocks_and_skips_reviewer():
    """When executor returns success=False, flow ends with BLOCKED (no reviewer)."""

    class FailingExec(ExecutorNode):
        def exec(self, prep_result):
            return {
                "success": False,
                "output": "",
                "error": "agent failed",
                "prompt": "x",
            }

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / ".rtw" / "runs" / "t"
        run_dir.mkdir(parents=True)
        (run_dir / "SUBTASK.md").write_text("# S\n")
        state = make_state(workspace=tmp, run_dir=str(run_dir))
        flow = Flow(start=FailingExec(MagicMock()))
        flow.run(state)
    assert state.status == FlowStatus.BLOCKED
    assert "agent failed" in (state.blocking_reason or "")


def test_flow_node_raise_sets_failed_and_reraises():
    """When a node raises, flow sets FAILED and re-raises."""

    class FailingNode(Node):
        def exec(self, prep_result):
            raise ValueError("boom")

    flow = Flow(start=FailingNode("Failing"))
    state = make_state()
    with pytest.raises(ValueError, match="boom"):
        flow.run(state)
    assert state.status == FlowStatus.FAILED
    assert "boom" in (state.blocking_reason or "")


def test_architect_flow_completes_with_mock_agent():
    """Full architect flow with mock agent (Planner writes COMPLETED) ends in one iteration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / ".rtw" / "runs" / "test"
        run_dir.mkdir(parents=True)
        (run_dir / "TASK.md").write_text("# Task\n")
        agent = MockAgentBackend()
        flow = make_architect_flow(agent)
        state = make_state(workspace=tmpdir, run_dir=str(run_dir))
        result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED
    assert result.current_iteration == 1

"""Core flow and node execution."""

import tempfile

from helpers import MockAgentBackend, make_architect_flow, make_state

from rtw.core import Flow, FlowStatus, Node, SharedState
from rtw.storage import StateStorage


class CounterNode(Node):
    """Node that increments a counter until max_count."""

    def __init__(self, name: str, max_count: int = 3):
        super().__init__(name)
        self.max_count = max_count

    def exec(self, prep_result):
        return None

    def post(self, state: SharedState, prep_result, exec_result) -> str | None:
        state.current_iteration += 1
        if state.current_iteration >= self.max_count:
            return None
        return "continue"


def test_basic_flow():
    """Flow runs until node returns None."""
    node = CounterNode("counter", max_count=3)
    node.on("continue") >> node
    flow = Flow(start=node)
    state = SharedState(task_file="test.md", task_content="test", workspace="/tmp")
    result = flow.run(state)
    assert result.current_iteration == 3


def test_flow_stops_at_max_iterations():
    """Flow stops at max_iterations and sets BLOCKED."""
    node = CounterNode("counter", max_count=100)
    node.on("continue") >> node
    flow = Flow(start=node)
    state = SharedState(
        task_file="test.md", task_content="test", workspace="/tmp", max_iterations=5
    )
    result = flow.run(state)
    assert result.current_iteration <= 5
    assert result.status == FlowStatus.BLOCKED


def test_architect_flow_completes_with_mock_agent():
    """Full plan→execute→review loop completes with mock agent."""
    agent = MockAgentBackend(
        responses={
            "architect": '{"summary": "Plan", "steps": [{"id": 1, "description": "Do thing", "type": "create", "target": "file.py", "details": "details"}]}',
            "reviewer": '{"verdict": "approve", "score": 90, "summary": "Good", "assessment": "Done.", "blocking_reason": null}',
        }
    )
    flow = make_architect_flow(agent)
    state = make_state()
    result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED
    assert result.current_iteration == 1


def test_state_save_and_load():
    """StateStorage save/load round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "test_run")
        state = SharedState(task_file="task.md", task_content="Test", workspace=tmpdir)
        state.current_iteration = 2
        state.add_artifact("test.py", "created")
        storage.save(state)
        loaded = storage.load()
        assert loaded is not None
        assert loaded.current_iteration == 2
        assert len(loaded.artifacts) == 1
        assert loaded.artifacts[0].path == "test.py"

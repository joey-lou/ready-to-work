"""Tests for core flow functionality."""

import tempfile

from rtw.architect import BuilderNode, PlannerNode, ReviewerNode
from rtw.core import Flow, FlowStatus, Node, SharedState
from rtw.llm import MockLLMClient
from rtw.storage import StateStorage


class CounterNode(Node):
    """Simple node that increments a counter."""

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
    """Test simple flow execution."""
    node = CounterNode("counter", max_count=3)
    node.on("continue") >> node

    flow = Flow(start=node)
    state = SharedState(task_file="test.md", task_content="test", workspace="/tmp")

    result = flow.run(state)

    assert result.current_iteration == 3


def test_flow_max_iterations():
    """Test that flow stops at max iterations."""
    node = CounterNode("counter", max_count=100)
    node.on("continue") >> node

    flow = Flow(start=node)
    state = SharedState(
        task_file="test.md",
        task_content="test",
        workspace="/tmp",
        max_iterations=5,
    )

    result = flow.run(state)

    assert result.current_iteration <= 5
    assert result.status == FlowStatus.BLOCKED


def test_architect_flow_mock():
    """Test full architect flow with mock LLM."""
    mock_responses = {
        "architect": '{"summary": "Test plan", "steps": [{"id": 1, "description": "Do thing", "type": "create", "target": "file.py", "details": "details"}], "dependencies": [], "risks": [], "estimated_complexity": "low"}',
        "developer": '{"completed_steps": [{"step_id": 1, "status": "completed", "action_taken": "Did thing", "files_affected": ["file.py"], "notes": ""}], "artifacts_created": [{"path": "file.py", "action": "created"}], "issues_encountered": [], "next_steps_suggested": []}',
        "reviewer": '{"verdict": "approve", "score": 90, "summary": "Good job", "strengths": ["works"], "issues": [], "feedback": "", "blocking_reason": null}',
    }

    llm = MockLLMClient(responses=mock_responses)

    planner = PlannerNode(llm)
    builder = BuilderNode(llm)
    reviewer = ReviewerNode(llm)

    planner.on("build") >> builder
    builder.on("review") >> reviewer
    reviewer.on("plan") >> planner

    flow = Flow(start=planner)
    state = SharedState(
        task_file="test.md",
        task_content="Build something cool",
        workspace="/tmp",
    )

    result = flow.run(state)

    assert result.status == FlowStatus.COMPLETED
    assert result.current_iteration == 1
    assert len(result.artifacts) == 1


def test_state_persistence():
    """Test state save and load."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "test_run")

        state = SharedState(
            task_file="task.md",
            task_content="Test content",
            workspace=tmpdir,
        )
        state.current_iteration = 3
        state.add_artifact("test.py", "created")

        storage.save(state)

        loaded = storage.load()
        assert loaded is not None
        assert loaded.current_iteration == 3
        assert len(loaded.artifacts) == 1
        assert loaded.artifacts[0].path == "test.py"


def test_state_iteration_tracking():
    """Test that iteration records are tracked correctly."""
    state = SharedState(
        task_file="test.md",
        task_content="test",
        workspace="/tmp",
    )

    record1 = state.start_iteration()
    record1.plan = {"step": 1}

    record2 = state.start_iteration()
    record2.plan = {"step": 2}

    assert state.current_iteration == 2
    assert len(state.history) == 2
    assert state.history[0].plan == {"step": 1}
    assert state.history[1].plan == {"step": 2}

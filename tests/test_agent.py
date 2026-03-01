"""Agent interface: AgentResult and MockAgentBackend."""

import json
from pathlib import Path

from helpers import MockAgentBackend

from rtw.agent import AgentResult


def test_agent_result_success():
    """AgentResult with success=True and output."""
    r = AgentResult(success=True, output="Done.")
    assert r.success is True
    assert r.output == "Done."
    assert r.error is None


def test_agent_result_failure():
    """AgentResult with success=False and error."""
    r = AgentResult(success=False, output="stderr", error="timeout")
    assert r.success is False
    assert r.error == "timeout"


def test_mock_agent_name():
    """MockAgentBackend.name is 'mock'."""
    assert MockAgentBackend().name == "mock"


def test_mock_agent_execute_returns_success():
    """Mock execute returns AgentResult(success=True)."""
    agent = MockAgentBackend()
    result = agent.execute(Path("/tmp"), "Hello", run_dir=None)
    assert result.success is True
    assert result.output == "Done."


def test_mock_agent_planner_writes_state_and_docs(tmp_path):
    """When prompt contains 'Planner', mock writes state.json, PLAN.md, SUBTASK.md under run_dir."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent = MockAgentBackend(plan_status="COMPLETED")
    agent.execute(Path("/ws"), "You are the Planner. ...", run_dir=run_dir)
    state_file = run_dir / "state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data.get("plan_status") == "COMPLETED"
    assert data.get("blocking_reason") is None
    assert (run_dir / "PLAN.md").exists()
    assert (run_dir / "SUBTASK.md").exists()


def test_mock_agent_reviewer_writes_subtask_status(tmp_path):
    """When prompt contains 'Reviewer', mock sets subtask_status PASSED in state.json."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "state.json").write_text('{"plan_status":"IN_PROGRESS"}')
    agent = MockAgentBackend()
    agent.execute(Path("/ws"), "You are the Reviewer. ...", run_dir=run_dir)
    data = json.loads((run_dir / "state.json").read_text())
    assert data.get("subtask_status") == "PASSED"


def test_mock_agent_side_effect_called():
    """When side_effect is set, it is called with (workspace, prompt, run_dir)."""
    seen = []
    agent = MockAgentBackend(
        side_effect=lambda w, p, r: seen.append((str(w), p[:10], str(r) if r else None))
    )
    agent.execute(Path("/ws"), "Hello world", run_dir=Path("/run"))
    assert len(seen) == 1
    assert seen[0][0] == "/ws"
    assert seen[0][1] == "Hello worl"  # prompt "Hello world" -> first 10 chars
    assert seen[0][2] == "/run"

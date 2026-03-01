"""Integration: full run_task/resume flows and architect loop with persistence."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from helpers import MockAgentBackend, make_architect_flow, make_state

from rtw.agent import AgentResult
from rtw.core import FlowStatus, SharedState
from rtw.storage import StateStorage


def test_run_task_flow_exception_returns_one():
    """run_task when flow raises returns 1."""
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "task.md").write_text("Do something")
        agent = MockAgentBackend(
            side_effect=lambda w, p, r=None: (_ for _ in ()).throw(RuntimeError("crash"))
        )
        with patch("rtw.cli.create_agent", return_value=agent):
            assert run_task(Path(tmpdir) / "task.md", Path(tmpdir), max_iterations=5) == 1


def test_run_task_keyboard_interrupt_returns_130():
    """run_task on KeyboardInterrupt returns 130 and saves state."""
    from rtw.cli import run_task

    call_count = {"n": 0}

    def interrupt_on_second(workspace, prompt, run_dir=None):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise KeyboardInterrupt

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "task.md").write_text("Do something")
        with patch(
            "rtw.cli.create_agent",
            return_value=MockAgentBackend(
                plan_status="IN_PROGRESS", side_effect=interrupt_on_second
            ),
        ):
            assert run_task(Path(tmpdir) / "task.md", Path(tmpdir), max_iterations=5) == 130


def test_resume_run_completes():
    """resume_run loads state and completes with mock agent."""
    from rtw.cli import resume_run

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "resume_test")
        storage.initialize_task_doc("Do something")
        storage.save(
            SharedState(workspace=tmpdir, run_dir=str(storage.base_dir), status=FlowStatus.BLOCKED)
        )
        with patch("rtw.cli.create_agent", return_value=MockAgentBackend()):
            assert resume_run(Path(tmpdir), run_id="resume_test") == 0


def test_resume_run_no_prior_runs_returns_one():
    """resume_run with no runs returns 1."""
    from rtw.cli import resume_run

    with tempfile.TemporaryDirectory() as tmpdir:
        assert resume_run(Path(tmpdir), run_id=None) == 1


def test_two_iteration_cycle_then_complete():
    """Architect flow: planner IN_PROGRESS -> executor -> reviewer PASSED -> planner COMPLETED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / ".rtw" / "runs" / "test"
        run_dir.mkdir(parents=True)
        (run_dir / "TASK.md").write_text("# Task\n")
        call_count = {"n": 0}
        default_run_dir = run_dir

        def custom_execute(workspace, prompt, run_dir=None):
            target = Path(run_dir) if run_dir is not None else default_run_dir
            target.mkdir(parents=True, exist_ok=True)
            state_file = target / "state.json"
            data = json.loads(state_file.read_text()) if state_file.exists() else {}
            if "Planner" in prompt:
                call_count["n"] += 1
                data["plan_status"] = "COMPLETED" if call_count["n"] >= 2 else "IN_PROGRESS"
                data["blocking_reason"] = None
                (target / "PLAN.md").write_text("# Plan\n")
                (target / "SUBTASK.md").write_text("# Subtask\n")
            if "Reviewer" in prompt:
                data["subtask_status"] = "PASSED"
                data["blocking_reason"] = None
            state_file.write_text(json.dumps(data, indent=2))
            return AgentResult(success=True, output="Ok")

        agent = MockAgentBackend()
        agent.execute = custom_execute
        flow = make_architect_flow(agent)
        state = make_state(workspace=tmpdir, run_dir=str(run_dir), max_iterations=5)
        result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED
    assert result.current_iteration >= 2


def test_persistence_writes_iter_snapshots_on_reviewer_passed():
    """When reviewer passes, on_state_change (save) writes iter-NNN snapshots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / ".rtw" / "runs" / "persist_test"
        run_dir.mkdir(parents=True)
        (run_dir / "TASK.md").write_text("# Task\n")
        storage = StateStorage(tmpdir, "persist_test")
        default_run_dir = run_dir

        def custom_execute(workspace, prompt, run_dir=None):
            target = Path(run_dir) if run_dir is not None else default_run_dir
            target.mkdir(parents=True, exist_ok=True)
            state_file = target / "state.json"
            d = json.loads(state_file.read_text()) if state_file.exists() else {}
            if "Planner" in prompt:
                d["plan_status"] = "IN_PROGRESS"
                d["blocking_reason"] = None
                (target / "PLAN.md").write_text("# Plan\n")
                (target / "SUBTASK.md").write_text("# Subtask\n")
            if "Reviewer" in prompt:
                d["subtask_status"] = "PASSED"
                d["blocking_reason"] = None
            state_file.write_text(json.dumps(d, indent=2))
            return AgentResult(success=True, output="Ok")

        agent = MockAgentBackend()
        agent.execute = custom_execute
        flow = make_architect_flow(agent, on_state_change=storage.save)
        flow.run(state=make_state(workspace=tmpdir, run_dir=str(run_dir), max_iterations=5))
        snapshots = list(storage.history_dir.glob("iter-*"))
        assert any("iter-001" in f.name for f in snapshots)

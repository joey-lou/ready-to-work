"""Integration tests: flow + CLI + persistence."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from helpers import (
    APPROVE_RESPONSE,
    ITERATE_RESPONSE,
    PLAN_RESPONSE,
    MockAgentBackend,
    make_architect_flow,
    make_state,
)

from rtw.core import Flow, FlowStatus, Node, SharedState
from rtw.storage import StateStorage


def _tmp_state(tmpdir: str, **kwargs) -> SharedState:
    defaults = {
        "task_file": "task.md",
        "task_content": "Do something",
        "workspace": tmpdir,
    }
    defaults.update(kwargs)
    return SharedState(**defaults)


def test_run_task_completes_returns_zero():
    """run_task with mock agent (patched) completes and returns 0."""
    from rtw.cli import run_task

    agent = MockAgentBackend(responses={"architect": PLAN_RESPONSE, "reviewer": APPROVE_RESPONSE})
    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Build something")
        with patch("rtw.cli.create_agent", return_value=agent):
            result = run_task(
                task_file=task_file,
                workspace=Path(tmpdir),
                max_iterations=5,
            )
    assert result == 0


def test_run_task_missing_file_returns_one():
    """run_task with missing task file returns 1."""
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_task(
            task_file=Path(tmpdir) / "nonexistent.md",
            workspace=Path(tmpdir),
            max_iterations=1,
        )
    assert result == 1


def test_run_task_flow_exception_returns_one():
    """run_task when flow raises returns 1 and saves state."""
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Do something")
        agent = MockAgentBackend(
            side_effect=lambda p, s: (_ for _ in ()).throw(RuntimeError("crash"))
        )
        with patch("rtw.cli.create_agent", return_value=agent):
            result = run_task(
                task_file=task_file,
                workspace=Path(tmpdir),
                max_iterations=5,
            )
    assert result == 1


def test_run_task_blocked_returns_two():
    """run_task when flow ends BLOCKED (e.g. max_iterations) returns 2."""
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Do something")
        agent = MockAgentBackend(
            responses={
                "architect": PLAN_RESPONSE,
                "reviewer": ITERATE_RESPONSE,
            }
        )
        with patch("rtw.cli.create_agent", return_value=agent):
            result = run_task(
                task_file=task_file,
                workspace=Path(tmpdir),
                max_iterations=1,
            )
    assert result == 2


def test_run_task_keyboard_interrupt_returns_130():
    """run_task on KeyboardInterrupt returns 130 and saves state."""
    from rtw.cli import run_task

    call_count = {"n": 0}

    def interrupt_on_second(prompt, system):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise KeyboardInterrupt
        return PLAN_RESPONSE

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Do something")
        agent = MockAgentBackend(side_effect=interrupt_on_second)
        with patch("rtw.cli.create_agent", return_value=agent):
            result = run_task(
                task_file=task_file,
                workspace=Path(tmpdir),
                max_iterations=5,
            )
    assert result == 130


def test_resume_run_completes():
    """resume_run loads state and completes with mock."""
    from rtw.cli import resume_run

    with tempfile.TemporaryDirectory() as tmpdir:
        run_id = "resume_test"
        storage = StateStorage(tmpdir, run_id)
        state = SharedState(
            task_file=str(Path(tmpdir) / "task.md"),
            task_content="Do something",
            workspace=tmpdir,
            status=FlowStatus.BLOCKED,
        )
        Path(tmpdir, "task.md").write_text("Do something")
        storage.save(state)
        agent = MockAgentBackend(
            responses={"architect": PLAN_RESPONSE, "reviewer": APPROVE_RESPONSE}
        )
        with patch("rtw.cli.create_agent", return_value=agent):
            result = resume_run(workspace=Path(tmpdir), run_id=run_id)
    assert result == 0


def test_resume_run_no_prior_runs_returns_one():
    """resume_run with no runs returns 1."""
    from rtw.cli import resume_run

    with tempfile.TemporaryDirectory() as tmpdir:
        result = resume_run(workspace=Path(tmpdir), run_id=None)
    assert result == 1


def test_list_runs_exits_zero():
    """list_runs returns 0."""
    from rtw.cli import list_runs

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "run1")
        state = _tmp_state(tmpdir, status=FlowStatus.COMPLETED)
        storage.save(state)
        result = list_runs(Path(tmpdir))
    assert result == 0


def test_two_iteration_cycle_then_complete():
    """Flow runs two iterations when reviewer first iterates then approves."""
    verdicts = [ITERATE_RESPONSE, APPROVE_RESPONSE]
    n = {"i": 0}

    def side_effect(prompt, system):
        if system and "code reviewer" in (system or "").lower():
            idx = n["i"]
            n["i"] += 1
            return verdicts[min(idx, len(verdicts) - 1)]
        return PLAN_RESPONSE

    agent = MockAgentBackend(side_effect=side_effect)
    flow = make_architect_flow(agent)
    state = make_state(max_iterations=5)
    result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED
    assert result.current_iteration >= 2


def test_persistence_writes_iter_files():
    """Flow with on_state_change writes iter_*.json per iteration."""
    verdicts = [ITERATE_RESPONSE, APPROVE_RESPONSE]
    n = {"i": 0}

    def side_effect(prompt, system):
        if system and "code reviewer" in (system or "").lower():
            idx = n["i"]
            n["i"] += 1
            return verdicts[min(idx, len(verdicts) - 1)]
        return PLAN_RESPONSE

    agent = MockAgentBackend(side_effect=side_effect)
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "persist_test")
        state = _tmp_state(tmpdir, max_iterations=5)
        flow = make_architect_flow(agent, on_state_change=storage.save)
        flow.run(state)
        iter_files = sorted(storage.history_dir.glob("iter_*.json"))
        assert len(iter_files) >= 2
        assert any(f.name == "iter_001.json" for f in iter_files)
        assert any(f.name == "iter_002.json" for f in iter_files)


def test_node_exception_sets_failed_and_reraises():
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


def test_keyboard_interrupt_propagates():
    """KeyboardInterrupt from node propagates out of flow.run()."""

    class InterruptNode(Node):
        def exec(self, prep_result):
            raise KeyboardInterrupt

    flow = Flow(start=InterruptNode("Kbd"))
    state = make_state()
    with pytest.raises(KeyboardInterrupt):
        flow.run(state)


def test_report_final_status_exit_codes():
    """_report_final_status returns 0/1/2 for COMPLETED/other/BLOCKED."""
    import logging

    from rtw.cli import _report_final_status

    log = logging.getLogger("test")
    assert _report_final_status(log, make_state(status=FlowStatus.COMPLETED)) == 0
    assert _report_final_status(log, make_state(status=FlowStatus.FAILED)) == 1
    state_blocked = make_state(status=FlowStatus.BLOCKED)
    state_blocked.blocking_reason = "Stuck"
    assert _report_final_status(log, state_blocked) == 2

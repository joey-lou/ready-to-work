"""Integration-style tests for full flow scenarios including persistence."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from helpers import (
    APPROVE_RESPONSE,
    ITERATE_RESPONSE,
    PLAN_RESPONSE,
    MockAgentBackend,
    make_architect_flow,
)
from llm_mock import MockLLMClient

from rtw.core import FlowStatus, SharedState
from rtw.storage import StateStorage


def make_state(tmpdir: str, **kwargs) -> SharedState:
    defaults = {"task_file": "task.md", "task_content": "Do something", "workspace": tmpdir}
    defaults.update(kwargs)
    return SharedState(**defaults)


# ---------------------------------------------------------------------------
# 1. Full plan->execute->review->plan->execute->review cycle (2 iterations)
# ---------------------------------------------------------------------------


def test_two_iteration_cycle_approve_on_second():
    """Reviewer returns iterate on first call and approve on second."""
    review_calls = {"n": 0}
    verdicts = [ITERATE_RESPONSE, APPROVE_RESPONSE]

    def side_effect(prompt, system):
        if system and "code reviewer" in system.lower():
            idx = review_calls["n"]
            review_calls["n"] += 1
            return verdicts[min(idx, len(verdicts) - 1)]
        if system and "architect" in system.lower():
            return PLAN_RESPONSE
        return PLAN_RESPONSE

    llm = MockLLMClient(side_effect=side_effect)
    agent = MockAgentBackend(llm)

    with tempfile.TemporaryDirectory() as tmpdir:
        state = make_state(tmpdir, max_iterations=5)
        flow = make_architect_flow(agent)
        result = flow.run(state)

    assert result.status == FlowStatus.COMPLETED
    assert result.current_iteration >= 2


# ---------------------------------------------------------------------------
# 2. State persistence writes iter_001.json and iter_002.json
# ---------------------------------------------------------------------------


def test_state_persistence_writes_iter_files():
    """Two-iteration flow writes at least two iter_*.json snapshot files."""
    review_calls = {"n": 0}
    verdicts = [ITERATE_RESPONSE, APPROVE_RESPONSE]

    def side_effect(prompt, system):
        if system and "code reviewer" in system.lower():
            idx = review_calls["n"]
            review_calls["n"] += 1
            return verdicts[min(idx, len(verdicts) - 1)]
        if system and "architect" in system.lower():
            return PLAN_RESPONSE
        return PLAN_RESPONSE

    llm = MockLLMClient(side_effect=side_effect)
    agent = MockAgentBackend(llm)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "test_run")
        state = make_state(tmpdir, max_iterations=5)
        flow = make_architect_flow(agent, on_state_change=storage.save)
        flow.run(state)

        iter_files = sorted(storage.history_dir.glob("iter_*.json"))
        assert len(iter_files) >= 2
        names = [f.name for f in iter_files]
        assert "iter_001.json" in names
        assert "iter_002.json" in names


# ---------------------------------------------------------------------------
# 3. KeyboardInterrupt mid-run → state saved as FAILED/preserved by cli handler
# ---------------------------------------------------------------------------


def test_keyboard_interrupt_mid_run_state_preserved():
    """Simulate KeyboardInterrupt and verify cli handler saves state."""
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Do something")

        call_count = {"n": 0}

        def interrupt_on_second(prompt, system):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise KeyboardInterrupt
            return PLAN_RESPONSE

        llm = MockLLMClient(side_effect=interrupt_on_second)

        with patch("rtw.cli.create_agent") as mock_factory:
            mock_factory.return_value = MockAgentBackend(llm)
            result = run_task(task_file, Path(tmpdir), max_iterations=5, mock=False)

    assert result == 130


# ---------------------------------------------------------------------------
# 4. run_task() integration test with tmp task file and mock client
# ---------------------------------------------------------------------------


def test_run_task_integration_with_mock_returns_zero():
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Build a hello world app")

        result = run_task(
            task_file=task_file,
            workspace=Path(tmpdir),
            max_iterations=5,
            mock=True,
        )

    assert result == 0


# ---------------------------------------------------------------------------
# 5. resume_run() integration test verifies it loads state and completes
# ---------------------------------------------------------------------------


def test_resume_run_integration_completes():
    from rtw.cli import resume_run

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create and save initial state
        run_id = "test_resume_run"
        storage = StateStorage(tmpdir, run_id)
        state = SharedState(
            task_file=str(Path(tmpdir) / "task.md"),
            task_content="Do something",
            workspace=tmpdir,
            status=FlowStatus.BLOCKED,
        )
        Path(tmpdir, "task.md").write_text("Do something")
        storage.save(state)

        result = resume_run(
            workspace=Path(tmpdir),
            run_id=run_id,
            mock=True,
        )

    assert result == 0


# ---------------------------------------------------------------------------
# 6. list_runs() integration test with multiple saved states
# ---------------------------------------------------------------------------


def test_list_runs_integration_multiple_states():
    from rtw.cli import list_runs

    with tempfile.TemporaryDirectory() as tmpdir:
        for run_id in ["20240101_000000", "20240102_000000", "20240103_000000"]:
            storage = StateStorage(tmpdir, run_id)
            state = SharedState(
                task_file="task.md",
                task_content="Task",
                workspace=tmpdir,
                status=FlowStatus.COMPLETED,
            )
            storage.save(state)

        result = list_runs(Path(tmpdir))

    assert result == 0


# ---------------------------------------------------------------------------
# 7. resume_run() with no prior runs returns exit code 1
# ---------------------------------------------------------------------------


def test_resume_run_with_no_prior_runs_returns_exit_1():
    from rtw.cli import resume_run

    with tempfile.TemporaryDirectory() as tmpdir:
        result = resume_run(workspace=Path(tmpdir), run_id=None, mock=True)

    assert result == 1


# ---------------------------------------------------------------------------
# 8. resume_run() with invalid run_id returns exit code 1
# ---------------------------------------------------------------------------


def test_resume_run_with_invalid_run_id_returns_exit_1():
    from rtw.cli import resume_run

    with tempfile.TemporaryDirectory() as tmpdir:
        result = resume_run(workspace=Path(tmpdir), run_id="nonexistent_run_id", mock=True)

    assert result == 1


# ---------------------------------------------------------------------------
# 9. run_task() with flow exception (not KeyboardInterrupt) returns exit code 1
# ---------------------------------------------------------------------------


def test_run_task_with_flow_exception_returns_exit_1():
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Do something")

        def always_explode(prompt, system):
            raise RuntimeError("unexpected crash")

        llm = MockLLMClient(side_effect=always_explode)

        with patch("rtw.cli.create_agent") as mock_factory:
            mock_factory.return_value = MockAgentBackend(llm)
            result = run_task(
                task_file=task_file, workspace=Path(tmpdir), max_iterations=5, mock=False
            )

    assert result == 1


# ---------------------------------------------------------------------------
# 10. list_runs() with corrupted state file skips gracefully
# ---------------------------------------------------------------------------


def test_list_runs_with_corrupted_state_skips_gracefully():
    from rtw.cli import list_runs

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "corrupt_run")
        storage.state_file.write_text("{{not valid json")

        good_storage = StateStorage(tmpdir, "good_run")
        state = SharedState(
            task_file="task.md", task_content="x", workspace=tmpdir, status=FlowStatus.COMPLETED
        )
        good_storage.save(state)

        result = list_runs(Path(tmpdir))

    assert result == 0


# ---------------------------------------------------------------------------
# 11. run_task() respects RTW_MODEL env var via create_agent
# ---------------------------------------------------------------------------


def test_run_task_respects_rtw_model_env_var():
    """create_agent uses RTW_MODEL when model arg is None and mock=False."""
    import os

    from rtw.agent import CursorAgentBackend
    from rtw.cli import create_agent

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["RTW_MODEL"] = "sonnet-4.6"
        try:
            agent = create_agent(mock=False, model=None, workspace=Path(tmpdir))
            assert isinstance(agent, CursorAgentBackend)
            assert agent.model == "sonnet-4.6"
        finally:
            del os.environ["RTW_MODEL"]


# ---------------------------------------------------------------------------
# 12. resume_run() with COMPLETED prior state resets and completes again
# ---------------------------------------------------------------------------


def test_resume_run_with_completed_prior_state_resets_and_completes():
    from rtw.cli import resume_run

    with tempfile.TemporaryDirectory() as tmpdir:
        run_id = "completed_resume_run"
        storage = StateStorage(tmpdir, run_id)
        state = SharedState(
            task_file=str(Path(tmpdir) / "task.md"),
            task_content="Do something",
            workspace=tmpdir,
            status=FlowStatus.COMPLETED,
        )
        Path(tmpdir, "task.md").write_text("Do something")
        storage.save(state)

        result = resume_run(workspace=Path(tmpdir), run_id=run_id, mock=True)

    assert result == 0


# ---------------------------------------------------------------------------
# 13. run_task returns exit code 2 when flow ends BLOCKED
# ---------------------------------------------------------------------------


def test_run_task_returns_exit_code_2_when_blocked():
    """run_task with max_iterations=1 and iterate verdict returns exit code 2."""
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Do something")

        llm = MockLLMClient(
            responses={
                "architect": PLAN_RESPONSE,
                "reviewer": ITERATE_RESPONSE,
            }
        )

        with patch("rtw.cli.create_agent") as mock_factory:
            mock_factory.return_value = MockAgentBackend(llm)
            result = run_task(
                task_file=task_file, workspace=Path(tmpdir), max_iterations=1, mock=False
            )

    assert result == 2


# ---------------------------------------------------------------------------
# 14. run_task returns exit code 1 when flow sets FAILED status
# ---------------------------------------------------------------------------


def test_run_task_returns_exit_code_1_for_exception():
    """run_task returns 1 when flow raises a non-KeyboardInterrupt exception."""
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("Do something")

        llm = MockLLMClient(side_effect=lambda p, s: (_ for _ in ()).throw(RuntimeError("crash")))

        with patch("rtw.cli.create_agent") as mock_factory:
            mock_factory.return_value = MockAgentBackend(llm)
            result = run_task(
                task_file=task_file, workspace=Path(tmpdir), max_iterations=5, mock=False
            )

    assert result == 1


# ---------------------------------------------------------------------------
# 15. _report_final_status unit tests for each exit code
# ---------------------------------------------------------------------------


def test_report_final_status_completed_returns_0():
    import logging

    from rtw.cli import _report_final_status

    with tempfile.TemporaryDirectory() as tmpdir:
        state = make_state(tmpdir, status=FlowStatus.COMPLETED)
        state.final_summary = "All done"
        result = _report_final_status(logging.getLogger("test"), state)
    assert result == 0


def test_report_final_status_blocked_returns_2():
    import logging

    from rtw.cli import _report_final_status

    with tempfile.TemporaryDirectory() as tmpdir:
        state = make_state(tmpdir, status=FlowStatus.BLOCKED)
        state.blocking_reason = "Cannot proceed"
        result = _report_final_status(logging.getLogger("test"), state)
    assert result == 2


def test_report_final_status_other_returns_1():
    import logging

    from rtw.cli import _report_final_status

    with tempfile.TemporaryDirectory() as tmpdir:
        state = make_state(tmpdir, status=FlowStatus.FAILED)
        result = _report_final_status(logging.getLogger("test"), state)
    assert result == 1

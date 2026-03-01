"""CLI: main() dispatch and run_task/resume exit codes."""

import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

from helpers import make_state

from rtw.core import FlowStatus, SharedState
from rtw.storage import StateStorage


def test_main_dispatches_list():
    """main() with 'list' calls list_runs and returns its exit code."""
    from rtw.cli import main

    with (
        patch("sys.argv", ["rtw", "list"]),
        patch("rtw.cli.list_runs", return_value=0) as m,
        patch("rtw.cli.setup_logging"),
    ):
        assert main() == 0
    m.assert_called_once()


def test_main_dispatches_run():
    """main() with 'run' and task file calls run_task."""
    from rtw.cli import main

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = Path(tmpdir) / "task.md"
        task_file.write_text("task")
        with (
            patch("sys.argv", ["rtw", "-w", tmpdir, "run", str(task_file)]),
            patch("rtw.cli.run_task", return_value=0) as m,
            patch("rtw.cli.setup_logging"),
        ):
            assert main() == 0
        m.assert_called_once()


def test_main_dispatches_resume():
    """main() with 'resume' calls resume_run."""
    from rtw.cli import main

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("sys.argv", ["rtw", "-w", tmpdir, "resume"]),
            patch("rtw.cli.resume_run", return_value=0) as m,
            patch("rtw.cli.setup_logging"),
        ):
            assert main() == 0
        m.assert_called_once()


def test_run_task_missing_file_returns_one():
    """run_task with missing task file returns 1."""
    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        assert run_task(Path(tmpdir) / "nonexistent.md", Path(tmpdir), max_iterations=1) == 1


def test_run_task_completes_returns_zero():
    """run_task with mock agent that completes returns 0."""
    from helpers import MockAgentBackend

    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "task.md").write_text("Build something")
        with patch("rtw.cli.create_agent", return_value=MockAgentBackend()):
            assert run_task(Path(tmpdir) / "task.md", Path(tmpdir), max_iterations=5) == 0


def test_run_task_blocked_returns_two():
    """run_task when flow ends BLOCKED (e.g. max_iterations) returns 2."""
    from helpers import MockAgentBackend

    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "task.md").write_text("Do something")
        with patch(
            "rtw.cli.create_agent", return_value=MockAgentBackend(plan_status="IN_PROGRESS")
        ):
            assert run_task(Path(tmpdir) / "task.md", Path(tmpdir), max_iterations=1) == 2


def test_list_runs_returns_zero():
    """list_runs with existing run returns 0."""
    from rtw.cli import list_runs

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "run1")
        storage.save(SharedState(workspace=tmpdir, run_dir=str(storage.base_dir)))
        assert list_runs(Path(tmpdir)) == 0


def test_report_final_status_exit_codes():
    """_report_final_status returns 0 for COMPLETED, 1 for other, 2 for BLOCKED."""
    from rtw.cli import _report_final_status

    log = logging.getLogger("test")
    assert _report_final_status(log, make_state(status=FlowStatus.COMPLETED), Path("/run")) == 0
    assert _report_final_status(log, make_state(status=FlowStatus.FAILED), Path("/run")) == 1
    state_blocked = make_state(status=FlowStatus.BLOCKED)
    state_blocked.blocking_reason = "Stuck"
    assert _report_final_status(log, state_blocked, Path(state_blocked.run_dir)) == 2

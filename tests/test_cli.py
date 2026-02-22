"""CLI argument parsing and main() dispatch."""

import argparse
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from rtw import __version__


def _parse_args(args: list[str]):
    """Parse CLI args without executing (reconstruct parser)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("-V", "--version", action="version", version=f"rtw {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-w", "--workspace", default=".")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run")
    run_p.add_argument("task_file")
    run_p.add_argument("--max-iter", type=int, default=10)
    run_p.add_argument("--model", default=None)
    sub.add_parser("list")
    res_p = sub.add_parser("resume")
    res_p.add_argument("--run-id", default=None)
    res_p.add_argument("--model", default=None)
    return parser.parse_args(args)


def test_verbose_flag():
    args = _parse_args(["-v", "list"])
    assert args.verbose is True


def test_version_exits_zero():
    with pytest.raises(SystemExit) as exc:
        _parse_args(["-V"])
    assert exc.value.code == 0


def test_run_subcommand():
    args = _parse_args(["run", "task.md", "--max-iter", "3"])
    assert args.command == "run"
    assert args.task_file == "task.md"
    assert args.max_iter == 3


def test_resume_subcommand_with_run_id():
    args = _parse_args(["resume", "--run-id", "20240101_120000"])
    assert args.command == "resume"
    assert args.run_id == "20240101_120000"


def test_list_subcommand():
    args = _parse_args(["list"])
    assert args.command == "list"


def test_workspace_default():
    args = _parse_args(["list"])
    assert args.workspace == "."


def test_model_passed_through_run():
    args = _parse_args(["run", "task.md", "--model", "claude-3-sonnet"])
    assert args.model == "claude-3-sonnet"


def test_model_passed_through_resume():
    args = _parse_args(["resume", "--model", "gpt-4"])
    assert args.model == "gpt-4"


def test_main_dispatches_list():
    from rtw.cli import main

    with (
        patch("sys.argv", ["rtw", "list"]),
        patch("rtw.cli.list_runs", return_value=0) as mock_list,
        patch("rtw.cli.setup_logging"),
    ):
        result = main()
    assert result == 0
    mock_list.assert_called_once()


def test_main_dispatches_run():
    from rtw.cli import main

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = str(Path(tmpdir) / "task.md")
        Path(task_file).write_text("task")
        with (
            patch("sys.argv", ["rtw", "-w", tmpdir, "run", task_file]),
            patch("rtw.cli.run_task", return_value=0) as mock_run,
            patch("rtw.cli.setup_logging"),
        ):
            result = main()
    assert result == 0
    mock_run.assert_called_once()


def test_main_dispatches_resume():
    from rtw.cli import main

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("sys.argv", ["rtw", "-w", tmpdir, "resume"]),
            patch("rtw.cli.resume_run", return_value=0) as mock_resume,
            patch("rtw.cli.setup_logging"),
        ):
            result = main()
    assert result == 0
    mock_resume.assert_called_once()

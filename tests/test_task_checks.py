"""TASK.md ## Checks parsing and optional command runner."""

from pathlib import Path

from rtw.core.task_checks import parse_task_check_commands, run_task_check_commands


def test_parse_checks_extracts_backtick_commands():
    task = """# T

## Checks
- `ruff check .`
- also `cargo fmt --check` and note
"""
    assert parse_task_check_commands(task) == ["ruff check .", "cargo fmt --check"]


def test_parse_checks_empty_without_section():
    assert parse_task_check_commands("# Hello\n") == []


def test_run_task_check_commands_noop_message():
    log = run_task_check_commands(Path("/"), [])
    assert "No ## Checks" in log


def test_run_task_check_commands_runs_in_workspace(tmp_path: Path):
    (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
    log = run_task_check_commands(tmp_path, ["test -f x.txt && echo ok"], timeout=5)
    assert "ok" in log
    assert "exit code: 0" in log

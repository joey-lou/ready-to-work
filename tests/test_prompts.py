"""Prompt templates: required placeholders and format."""

from pathlib import Path

from rtw.architect.prompts import EXECUTOR, PLANNER, REVIEWER


def test_planner_format_with_all_placeholders():
    """PLANNER.format() with all required keys produces non-empty string without braces."""
    out = PLANNER.format(
        state_path=Path("/run/state.json"),
        task="Build X",
        plan="Step 1",
        subtask="Implement step 1",
        iteration=1,
        max_iter=10,
        plan_path=Path("/run/PLAN.md"),
        subtask_path=Path("/run/SUBTASK.md"),
    )
    assert out
    assert "{" not in out or "state.json" in out
    assert "Build X" in out
    assert "Iteration 1 of 10" in out


def test_reviewer_format_with_all_placeholders():
    """REVIEWER.format() with all required keys produces non-empty string."""
    out = REVIEWER.format(
        state_path=Path("/run/state.json"),
        task="T",
        plan="P",
        subtask="S",
        changed_paths="- foo.py",
        file_contents_block="## foo.py\n```\ncode\n```",
        iteration=1,
        max_iter=10,
        subtask_path=Path("/run/SUBTASK.md"),
    )
    assert out
    assert "Reviewer" in out
    assert "foo.py" in out
    assert "Iteration 1 of 10" in out


def test_executor_format_with_all_placeholders():
    """EXECUTOR.format() with all required keys produces non-empty string."""
    out = EXECUTOR.format(
        workspace_path=Path("/project"),
        tmp_dir=Path("/project/.rtw/runs/1/tmp"),
        subtask_markdown="Implement feature X.",
    )
    assert out
    assert "Executor" in out
    assert "Implement feature X." in out
    assert "/project" in out or "project" in out

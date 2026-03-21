"""Prompt templates: required placeholders and format."""

from rtw.architect.prompts import EXECUTOR, PLANNER, REVIEWER


def test_planner_format_with_all_placeholders():
    """PLANNER.format() with all required keys produces non-empty string without braces."""
    out = PLANNER.format(
        run_dir_rel=".rtw/runs/1",
        tmp_dir_rel=".rtw/runs/1/tmp",
        task="Build X",
        plan="Step 1",
        subtask="Implement step 1",
        iteration=1,
        max_iter=10,
    )
    assert out
    assert "{" not in out or "state.json" in out
    assert "Build X" in out
    assert "Iteration 1 of 10" in out


def test_reviewer_format_with_all_placeholders():
    """REVIEWER.format() with all required keys produces non-empty string."""
    out = REVIEWER.format(
        run_dir_rel=".rtw/runs/1",
        task="T",
        plan="P",
        subtask="S",
        changed_paths="- foo.py",
        file_contents_block="## foo.py\n```\ncode\n```",
        iteration=1,
        max_iter=10,
    )
    assert out
    assert "Reviewer" in out
    assert "foo.py" in out
    assert "Iteration 1 of 10" in out


def test_executor_format_with_all_placeholders():
    """EXECUTOR.format() with all required keys produces non-empty string."""
    out = EXECUTOR.format(
        tmp_dir_rel=".rtw/runs/1/tmp",
        subtask_markdown="Implement feature X.",
    )
    assert out
    assert "Executor" in out
    assert "Implement feature X." in out
    assert "tmp" in out

"""Run directory paths: run_paths() and constants."""

from pathlib import Path

from rtw.core.paths import (
    PLAN_MD,
    STATE_JSON,
    SUBTASK_MD,
    SUMMARY_MD,
    TASK_MD,
    TRACES_DIR,
    run_paths,
)


def test_run_paths_returns_all_entries():
    """run_paths returns dict with run_dir, TASK, PLAN, SUBTASK, SUMMARY, state_file, traces_dir."""
    base = Path("/tmp/.rtw/runs/run1")
    paths = run_paths(base)
    assert paths["run_dir"] == base
    assert paths["TASK"] == base / TASK_MD
    assert paths["PLAN"] == base / PLAN_MD
    assert paths["SUBTASK"] == base / SUBTASK_MD
    assert paths["SUMMARY"] == base / SUMMARY_MD
    assert paths["state_file"] == base / STATE_JSON
    assert paths["traces_dir"] == base / TRACES_DIR


def test_run_paths_accepts_string():
    """run_paths accepts str path."""
    paths = run_paths("/tmp/run")
    assert paths["run_dir"] == Path("/tmp/run")
    assert paths["TASK"] == Path("/tmp/run") / TASK_MD


def test_constants_are_expected_filenames():
    """Path constants match expected run-dir filenames."""
    assert TASK_MD == "TASK.md"
    assert STATE_JSON == "state.json"
    assert TRACES_DIR == "traces"

"""Canonical paths for a run directory. Used by storage and architect nodes."""

from pathlib import Path

# Relative to run_dir
TASK_MD = "TASK.md"
PLAN_MD = "PLAN.md"
SUBTASK_MD = "SUBTASK.md"
SUMMARY_MD = "SUMMARY.md"
STATE_JSON = "state.json"
TRACES_DIR = "traces"


def run_paths(run_dir: str | Path) -> dict[str, Path]:
    """Return a dict of canonical paths under run_dir."""
    base = Path(run_dir)
    return {
        "run_dir": base,
        "TASK": base / TASK_MD,
        "PLAN": base / PLAN_MD,
        "SUBTASK": base / SUBTASK_MD,
        "SUMMARY": base / SUMMARY_MD,
        "state_file": base / STATE_JSON,
        "traces_dir": base / TRACES_DIR,
    }

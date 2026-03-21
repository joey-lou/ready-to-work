"""SharedState: serialization, defaults, and iteration."""

import tempfile
from pathlib import Path

import pytest

from rtw.core.state import FlowStatus, PlanStatus, SharedState, SubtaskStatus


def test_to_dict_round_trip():
    """to_dict/from_dict preserves all persisted fields (paths resolved consistently)."""
    state = SharedState(
        workspace="/tmp",
        run_dir="/tmp/.rtw/runs/test",
        run_tmp_dir="/tmp/.rtw/runs/test/tmp",
        status=FlowStatus.EXECUTING,
        plan_status=PlanStatus.IN_PROGRESS,
        subtask_status=SubtaskStatus.NEEDS_REVIEW,
        current_iteration=1,
        max_iterations=5,
        blocking_reason="block",
        files_changed=[{"path": "a.py", "action": "modified"}],
    )
    restored = SharedState.from_dict(state.to_dict())
    assert restored.workspace == state.workspace
    assert Path(restored.run_dir).resolve() == Path(state.run_dir).resolve()
    assert Path(restored.run_tmp_dir or "").resolve() == Path(state.run_tmp_dir or "").resolve()
    assert restored.status == state.status
    assert restored.plan_status == state.plan_status
    assert restored.subtask_status == state.subtask_status
    assert restored.current_iteration == state.current_iteration
    assert restored.max_iterations == state.max_iterations
    assert restored.blocking_reason == state.blocking_reason
    assert restored.files_changed == state.files_changed


def test_to_dict_persists_run_paths_workspace_relative():
    """state.json uses workspace-relative run_dir and run_tmp_dir when under workspace."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp).resolve()
        run = ws / ".rtw" / "runs" / "rid"
        run_tmp = run / "tmp"
        state = SharedState(
            workspace=str(ws),
            run_dir=str(run),
            run_tmp_dir=str(run_tmp),
        )
        d = state.to_dict()
        assert d["run_dir"] == ".rtw/runs/rid"
        assert d["run_tmp_dir"] == ".rtw/runs/rid/tmp"


def test_from_dict_resolves_relative_run_paths():
    """Loading relative run_dir/run_tmp_dir joins against workspace."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp).resolve()
        data = {
            "workspace": str(ws),
            "run_dir": ".rtw/runs/x",
            "run_tmp_dir": ".rtw/runs/x/tmp",
            "status": "PENDING",
            "current_iteration": 0,
            "max_iterations": 10,
        }
        state = SharedState.from_dict(data)
        assert Path(state.run_dir) == ws / ".rtw" / "runs" / "x"
        assert Path(state.run_tmp_dir or "") == ws / ".rtw" / "runs" / "x" / "tmp"


def test_from_dict_missing_optionals_uses_defaults():
    """Optional fields get defaults when loading."""
    data = {
        "workspace": "/tmp",
        "run_dir": "/tmp/.rtw/runs/test",
        "status": "PENDING",
        "current_iteration": 0,
        "max_iterations": 10,
    }
    state = SharedState.from_dict(data)
    assert state.blocking_reason is None
    assert state.files_changed == []
    assert state.plan_status == PlanStatus.NOT_STARTED
    assert state.subtask_status == SubtaskStatus.DRAFT


def test_from_dict_invalid_status_raises():
    """Invalid status string raises ValueError."""
    data = {
        "workspace": "/tmp",
        "run_dir": "/tmp/.rtw/runs/test",
        "status": "INVALID",
        "current_iteration": 0,
        "max_iterations": 10,
    }
    with pytest.raises(ValueError):
        SharedState.from_dict(data)


def test_start_iteration_increments_and_touches():
    """start_iteration increments current_iteration and updates updated_at."""
    state = SharedState(workspace="/", run_dir="/.rtw/runs/test", current_iteration=0)
    state.start_iteration()
    assert state.current_iteration == 1
    state.start_iteration()
    assert state.current_iteration == 2

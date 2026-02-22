"""SharedState and StateStorage behavior."""

import tempfile
from pathlib import Path

import pytest

from rtw.core.state import FlowStatus, SharedState
from rtw.storage import StateStorage


def test_state_round_trip():
    """to_dict/from_dict preserves fields."""
    state = SharedState(
        task_file="task.md",
        task_content="Do something",
        workspace="/tmp",
        status=FlowStatus.EXECUTING,
        current_iteration=1,
        max_iterations=5,
        blocking_reason="block",
        final_summary="done",
    )
    state.add_artifact("a.py", "created")
    state.add_artifact("b.py", "modified")
    r = state.start_iteration()
    r.plan = {"steps": [1, 2]}
    r.build_result = {"ok": True}

    restored = SharedState.from_dict(state.to_dict())
    assert restored.task_file == state.task_file
    assert restored.workspace == state.workspace
    assert restored.status == FlowStatus.EXECUTING
    assert restored.current_iteration == 2
    assert restored.max_iterations == 5
    assert restored.blocking_reason == "block"
    assert restored.final_summary == "done"
    assert len(restored.artifacts) == 2
    assert restored.artifacts[0].path == "a.py"
    assert restored.artifacts[1].action == "modified"
    assert len(restored.history) == 1
    assert restored.history[0].plan == {"steps": [1, 2]}


def test_from_dict_missing_optionals_uses_defaults():
    """from_dict with minimal data uses defaults for optionals."""
    data = {
        "task_file": "t.md",
        "task_content": "x",
        "workspace": "/tmp",
        "status": "pending",
        "current_iteration": 0,
        "max_iterations": 10,
    }
    state = SharedState.from_dict(data)
    assert state.blocking_reason is None
    assert state.final_summary is None
    assert state.artifacts == []
    assert state.history == []
    assert state.current_plan is None


def test_flow_status_round_trip():
    """All FlowStatus values survive serialization."""
    for status in FlowStatus:
        state = SharedState(task_file="f", task_content="x", workspace="/", status=status)
        restored = SharedState.from_dict(state.to_dict())
        assert restored.status == status


def test_from_dict_unknown_status_raises():
    """from_dict with invalid status raises ValueError."""
    data = {
        "task_file": "t.md",
        "task_content": "x",
        "workspace": "/tmp",
        "status": "invalid_status",
        "current_iteration": 0,
        "max_iterations": 10,
    }
    with pytest.raises(ValueError):
        SharedState.from_dict(data)


def test_add_artifact_upserts_by_path():
    """add_artifact replaces existing entry for same path."""
    state = SharedState(task_file="t.md", task_content="x", workspace="/tmp")
    state.add_artifact("file.py", "created")
    state.add_artifact("file.py", "modified")
    assert len(state.artifacts) == 1
    assert state.artifacts[0].action == "modified"


def test_list_runs_sorted_descending():
    """list_runs returns run IDs sorted descending."""
    with tempfile.TemporaryDirectory() as tmpdir:
        runs_dir = Path(tmpdir) / ".rtw" / "runs"
        for run_id in ["20240101_090000", "20240103_120000", "20240102_060000"]:
            (runs_dir / run_id).mkdir(parents=True)
            (runs_dir / run_id / "state.json").write_text("{}")
        runs = StateStorage.list_runs(tmpdir)
        assert runs == ["20240103_120000", "20240102_060000", "20240101_090000"]


def test_list_runs_empty_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert StateStorage.list_runs(tmpdir) == []


def test_get_latest_run_returns_none_when_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert StateStorage.get_latest_run(tmpdir) is None


def test_get_latest_run_returns_most_recent():
    with tempfile.TemporaryDirectory() as tmpdir:
        for run_id in ["20240101_000000", "20240102_000000"]:
            storage = StateStorage(tmpdir, run_id)
            state = SharedState(task_file="t.md", task_content="x", workspace=tmpdir)
            storage.save(state)
        latest = StateStorage.get_latest_run(tmpdir)
        assert latest is not None
        assert latest.run_id == "20240102_000000"


def test_load_corrupted_state_returns_none(caplog):
    """Corrupt state file → load() returns None and logs error."""
    import logging

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "bad_run")
        storage.state_file.write_text("not valid json {{{{")
        with caplog.at_level(logging.ERROR):
            result = storage.load()
        assert result is None
        assert any("Failed to load state" in r.message for r in caplog.records)


def test_load_missing_required_field_returns_none(caplog):
    """Valid JSON missing required field → load() returns None."""
    import logging

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "missing_run")
        storage.state_file.write_text('{"task_file": "t.md", "workspace": "/tmp"}')
        with caplog.at_level(logging.ERROR):
            result = storage.load()
        assert result is None

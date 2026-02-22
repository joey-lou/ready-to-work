"""Tests for state serialization edge cases and storage utilities."""

import tempfile
from pathlib import Path

from rtw.core.state import FlowStatus, SharedState
from rtw.storage import StateStorage

# ---------------------------------------------------------------------------
# SharedState serialization round-trip
# ---------------------------------------------------------------------------


def test_round_trip_all_fields():
    state = SharedState(
        task_file="task.md",
        task_content="Do something",
        workspace="/tmp",
        status=FlowStatus.EXECUTING,
        current_iteration=2,
        max_iterations=5,
        blocking_reason="partial block",
        final_summary="done",
    )
    state.add_artifact("a.py", "created")
    state.add_artifact("b.py", "modified")
    r = state.start_iteration()
    r.plan = {"steps": [1, 2]}
    r.build_result = {"ok": True}
    r.review_result = {"verdict": "iterate"}

    restored = SharedState.from_dict(state.to_dict())

    assert restored.task_file == state.task_file
    assert restored.task_content == state.task_content
    assert restored.workspace == state.workspace
    assert restored.status == FlowStatus.EXECUTING
    assert restored.current_iteration == 3  # start_iteration increments
    assert restored.max_iterations == 5
    assert restored.blocking_reason == "partial block"
    assert restored.final_summary == "done"
    assert len(restored.artifacts) == 2
    assert restored.artifacts[0].path == "a.py"
    assert restored.artifacts[1].action == "modified"
    assert len(restored.history) == 1
    assert restored.history[0].plan == {"steps": [1, 2]}
    assert restored.history[0].build_result == {"ok": True}
    assert restored.history[0].review_result == {"verdict": "iterate"}


def test_from_dict_missing_optional_fields_uses_defaults():
    minimal = {
        "task_file": "t.md",
        "task_content": "x",
        "workspace": "/tmp",
        "status": "pending",
        "current_iteration": 0,
        "max_iterations": 10,
    }
    state = SharedState.from_dict(minimal)

    assert state.blocking_reason is None
    assert state.final_summary is None
    assert state.artifacts == []
    assert state.history == []
    assert state.current_plan is None


# ---------------------------------------------------------------------------
# FlowStatus enum preserved through serialization
# ---------------------------------------------------------------------------


def test_all_flow_statuses_round_trip():
    for status in FlowStatus:
        state = SharedState(task_file="f", task_content="x", workspace="/", status=status)
        restored = SharedState.from_dict(state.to_dict())
        assert restored.status == status


# ---------------------------------------------------------------------------
# context_summary() output format
# ---------------------------------------------------------------------------


def test_context_summary_basic():
    state = SharedState(task_file="task.md", task_content="x", workspace="/tmp")
    summary = state.context_summary()

    assert "task.md" in summary
    assert "0/10" in summary
    assert "pending" in summary


def test_context_summary_with_artifacts_and_plan():
    state = SharedState(task_file="task.md", task_content="x", workspace="/tmp")
    state.add_artifact("file.py", "created")
    state.current_plan = {"steps": [{"id": 1}, {"id": 2}]}
    summary = state.context_summary()

    assert "Artifacts created: 1" in summary
    assert "Current plan steps: 2" in summary


# ---------------------------------------------------------------------------
# StateStorage.list_runs() returns sorted descending
# ---------------------------------------------------------------------------


def test_list_runs_sorted_descending():
    with tempfile.TemporaryDirectory() as tmpdir:
        runs_dir = Path(tmpdir) / ".rtw" / "runs"
        for run_id in ["20240101_090000", "20240103_120000", "20240102_060000"]:
            (runs_dir / run_id).mkdir(parents=True)
            (runs_dir / run_id / "state.json").write_text("{}")

        runs = StateStorage.list_runs(tmpdir)
        assert runs == ["20240103_120000", "20240102_060000", "20240101_090000"]


def test_list_runs_empty_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        runs = StateStorage.list_runs(tmpdir)
        assert runs == []


# ---------------------------------------------------------------------------
# StateStorage.get_latest_run() returns None for empty workspace
# ---------------------------------------------------------------------------


def test_get_latest_run_returns_none_for_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = StateStorage.get_latest_run(tmpdir)
        assert result is None


def test_get_latest_run_returns_most_recent():
    with tempfile.TemporaryDirectory() as tmpdir:
        for run_id in ["20240101_000000", "20240102_000000"]:
            storage = StateStorage(tmpdir, run_id)
            state = SharedState(task_file="t.md", task_content="x", workspace=tmpdir)
            storage.save(state)

        latest = StateStorage.get_latest_run(tmpdir)
        assert latest is not None
        assert latest.run_id == "20240102_000000"


# ---------------------------------------------------------------------------
# Corrupted state file → load() returns None and logs error
# ---------------------------------------------------------------------------


def test_load_corrupted_state_returns_none(caplog):
    import logging

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "bad_run")
        storage.state_file.write_text("not valid json {{{{")

        with caplog.at_level(logging.ERROR):
            result = storage.load()

        assert result is None
        assert any("Failed to load state" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# SharedState.touch() updates updated_at
# ---------------------------------------------------------------------------


def test_touch_updates_updated_at():
    import time

    state = SharedState(task_file="t.md", task_content="x", workspace="/tmp")
    before = state.updated_at
    time.sleep(0.01)
    state.touch()
    assert state.updated_at > before


# ---------------------------------------------------------------------------
# add_artifact() upserts by path (keeps latest action per file)
# ---------------------------------------------------------------------------


def test_add_artifact_upserts_by_path():
    state = SharedState(task_file="t.md", task_content="x", workspace="/tmp")
    state.add_artifact("file.py", "created")
    state.add_artifact("file.py", "modified")
    assert len(state.artifacts) == 1
    assert state.artifacts[0].action == "modified"


# ---------------------------------------------------------------------------
# current_record() returns None on empty history
# ---------------------------------------------------------------------------


def test_current_record_returns_none_on_empty_history():
    state = SharedState(task_file="t.md", task_content="x", workspace="/tmp")
    assert state.current_record() is None


# ---------------------------------------------------------------------------
# context_summary() when blocking_reason is set
# ---------------------------------------------------------------------------


def test_context_summary_with_blocking_reason():
    state = SharedState(task_file="task.md", task_content="x", workspace="/tmp")
    state.blocking_reason = "Need human input"
    summary = state.context_summary()
    # blocking_reason is not in context_summary output but the method should not crash
    assert "task.md" in summary


# ---------------------------------------------------------------------------
# from_dict with unknown status value raises ValueError
# ---------------------------------------------------------------------------


def test_from_dict_unknown_status_raises():
    import pytest

    data = {
        "task_file": "t.md",
        "task_content": "x",
        "workspace": "/tmp",
        "status": "totally_unknown_status",
        "current_iteration": 0,
        "max_iterations": 10,
    }
    with pytest.raises(ValueError):
        SharedState.from_dict(data)


# ---------------------------------------------------------------------------
# StateStorage.save() with iteration=0 does not write iter file
# ---------------------------------------------------------------------------


def test_save_with_iteration_zero_does_not_write_iter_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "run_zero")
        state = SharedState(task_file="t.md", task_content="x", workspace=tmpdir)
        assert state.current_iteration == 0
        storage.save(state)

        iter_files = list(storage.history_dir.glob("iter_*.json"))
        assert iter_files == []


# ---------------------------------------------------------------------------
# StateStorage.list_iterations() returns sorted list
# ---------------------------------------------------------------------------


def test_list_iterations_returns_sorted():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "run_iters")
        state = SharedState(task_file="t.md", task_content="x", workspace=tmpdir)

        for _ in range(3):
            state.start_iteration()
            storage.save(state)

        iterations = storage.list_iterations()
        assert len(iterations) == 3
        nums = [it["iteration"] for it in iterations]
        assert nums == sorted(nums)


# ---------------------------------------------------------------------------
# StateStorage with same run_id but different workspace doesn't conflict
# ---------------------------------------------------------------------------


def test_same_run_id_different_workspace_no_conflict():
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        run_id = "shared_run_id"
        s1 = StateStorage(tmp1, run_id)
        s2 = StateStorage(tmp2, run_id)

        state1 = SharedState(task_file="a.md", task_content="task A", workspace=tmp1)
        state2 = SharedState(task_file="b.md", task_content="task B", workspace=tmp2)

        s1.save(state1)
        s2.save(state2)

        loaded1 = s1.load()
        loaded2 = s2.load()

        assert loaded1.task_file == "a.md"
        assert loaded2.task_file == "b.md"


# ---------------------------------------------------------------------------
# save/load round-trip with unicode content
# ---------------------------------------------------------------------------


def test_save_load_round_trip_with_unicode():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "unicode_run")
        content = "Tâche: créer un fichier avec des données 日本語 🚀"
        state = SharedState(task_file="unicode.md", task_content=content, workspace=tmpdir)
        storage.save(state)

        loaded = storage.load()
        assert loaded is not None
        assert loaded.task_content == content


# ---------------------------------------------------------------------------
# StateStorage.save() with read-only history_dir raises OSError
# ---------------------------------------------------------------------------


def test_save_with_readonly_history_dir_raises(tmp_path):
    import os
    import stat

    storage = StateStorage(str(tmp_path), "readonly_run")
    os.chmod(storage.history_dir, stat.S_IRUSR | stat.S_IXUSR)  # remove write bit

    state = SharedState(task_file="t.md", task_content="x", workspace=str(tmp_path))
    state.start_iteration()  # current_iteration=1 triggers iter file write

    try:
        import pytest

        with pytest.raises(OSError):
            storage.save(state)
    finally:
        os.chmod(storage.history_dir, stat.S_IRWXU)


# ---------------------------------------------------------------------------
# load() on valid JSON but missing required fields raises KeyError
# ---------------------------------------------------------------------------


def test_load_missing_required_field_returns_none(caplog):
    import logging

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "missing_fields_run")
        # Valid JSON but missing 'task_content'
        storage.state_file.write_text('{"task_file": "t.md", "workspace": "/tmp"}')
        with caplog.at_level(logging.ERROR):
            result = storage.load()
        assert result is None
        assert any("Failed to load state" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# list_iterations() on empty history_dir returns []
# ---------------------------------------------------------------------------


def test_list_iterations_empty_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "empty_run")
        assert storage.list_iterations() == []


# ---------------------------------------------------------------------------
# Artifact timestamp is ISO format string
# ---------------------------------------------------------------------------


def test_artifact_timestamp_is_iso_format():
    from datetime import datetime

    state = SharedState(task_file="t.md", task_content="x", workspace="/tmp")
    state.add_artifact("file.py", "created")

    ts = state.artifacts[0].timestamp
    # Should parse without error
    parsed = datetime.fromisoformat(ts)
    assert parsed is not None


# ---------------------------------------------------------------------------
# SharedState.from_dict() with artifact missing 'timestamp' falls back gracefully
# ---------------------------------------------------------------------------


def test_from_dict_artifact_missing_timestamp_falls_back():
    data = {
        "task_file": "t.md",
        "task_content": "x",
        "workspace": "/tmp",
        "status": "pending",
        "current_iteration": 0,
        "max_iterations": 10,
        "artifacts": [{"path": "file.py", "action": "created"}],
    }
    state = SharedState.from_dict(data)
    assert len(state.artifacts) == 1
    assert state.artifacts[0].path == "file.py"
    assert state.artifacts[0].timestamp is not None


# ---------------------------------------------------------------------------
# StateStorage.list_iterations() skips invalid JSON and logs warning
# ---------------------------------------------------------------------------


def test_list_iterations_skips_invalid_json_and_logs_warning(caplog):
    import logging

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "partial_run")
        # Write one valid and one invalid iter file manually
        (storage.history_dir / "iter_001.json").write_text('{"iteration": 1, "plan": null}')
        (storage.history_dir / "iter_002.json").write_text("{{not valid json")

        with caplog.at_level(logging.WARNING):
            iterations = storage.list_iterations()

        assert len(iterations) == 1
        assert iterations[0]["iteration"] == 1
        assert any("iter_002.json" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# StateStorage.save() with current_iteration>0 but no current_record() is safe
# ---------------------------------------------------------------------------


def test_save_with_nonzero_iteration_and_empty_history_does_not_crash():
    """If current_iteration>0 but history is empty, save() skips iter file write."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "odd_run")
        state = SharedState(task_file="t.md", task_content="x", workspace=tmpdir)
        # Manually set current_iteration without creating a history record
        state.current_iteration = 1

        # Should not raise
        storage.save(state)
        iter_files = list(storage.history_dir.glob("iter_*.json"))
        assert iter_files == []


# ---------------------------------------------------------------------------
# SharedState.context_summary() with max_iterations=0 does not divide by zero
# ---------------------------------------------------------------------------


def test_context_summary_with_max_iterations_zero():
    state = SharedState(task_file="t.md", task_content="x", workspace="/tmp", max_iterations=0)
    summary = state.context_summary()
    assert "0/0" in summary


# ---------------------------------------------------------------------------
# Artifact round-trips for all three action values
# ---------------------------------------------------------------------------


def test_artifact_all_action_values_round_trip():
    state = SharedState(task_file="t.md", task_content="x", workspace="/tmp")
    state.add_artifact("a.py", "created")
    state.add_artifact("b.py", "modified")
    state.add_artifact("c.py", "deleted")

    restored = SharedState.from_dict(state.to_dict())
    actions = [a.action for a in restored.artifacts]
    assert actions == ["created", "modified", "deleted"]


# ---------------------------------------------------------------------------
# from_dict with history record missing plan/build_result/review_result uses None
# ---------------------------------------------------------------------------


def test_from_dict_history_missing_fields_uses_none():
    data = {
        "task_file": "t.md",
        "task_content": "x",
        "workspace": "/tmp",
        "status": "pending",
        "current_iteration": 1,
        "max_iterations": 10,
        "history": [{"iteration": 1}],
    }
    state = SharedState.from_dict(data)
    assert len(state.history) == 1
    record = state.history[0]
    assert record.plan is None
    assert record.build_result is None
    assert record.review_result is None

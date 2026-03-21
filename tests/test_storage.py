"""StateStorage: save/load, list_runs, iteration snapshots."""

import json
import tempfile
from pathlib import Path

from rtw.core.state import SharedState, SubtaskStatus
from rtw.storage import StateStorage


def test_save_and_load_round_trip():
    """Save state then load returns equivalent state with task_content from TASK.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "run1")
        storage.initialize_task_doc("# Task\nDo X.")
        state = SharedState(
            workspace=tmpdir,
            run_dir=str(storage.base_dir),
            run_tmp_dir=str(storage.tmp_dir),
            current_iteration=2,
        )
        storage.save(state)
        raw = json.loads(storage.state_file.read_text())
        assert raw["run_dir"] == ".rtw/runs/run1"
        assert raw["run_tmp_dir"] == ".rtw/runs/run1/tmp"
        loaded = storage.load()
    assert loaded is not None
    assert loaded.workspace == tmpdir
    assert Path(loaded.run_dir).resolve() == Path(storage.base_dir).resolve()
    assert loaded.current_iteration == 2
    assert loaded.task_content.strip().startswith("# Task")


def test_load_missing_file_returns_none():
    """Load when state.json does not exist returns None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "missing")
        assert storage.load() is None


def test_load_corrupted_returns_none(caplog):
    """Load when state.json is invalid JSON returns None and logs."""
    import logging

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "bad")
        storage.base_dir.mkdir(parents=True, exist_ok=True)
        storage.state_file.write_text("not json {{{")
        with caplog.at_level(logging.ERROR):
            assert storage.load() is None
        assert any("Failed to load" in r.message for r in caplog.records)


def test_load_missing_required_field_returns_none(caplog):
    """Load when state.json is missing required key returns None."""
    import logging

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "partial")
        storage.base_dir.mkdir(parents=True, exist_ok=True)
        storage.state_file.write_text('{"workspace": "/tmp"}')
        with caplog.at_level(logging.ERROR):
            assert storage.load() is None


def test_list_runs_returns_sorted_descending():
    """list_runs returns run IDs sorted newest first."""
    with tempfile.TemporaryDirectory() as tmpdir:
        runs_dir = Path(tmpdir) / ".rtw" / "runs"
        for run_id in ["20240101_090000", "20240103_120000", "20240102_060000"]:
            (runs_dir / run_id).mkdir(parents=True)
            (runs_dir / run_id / "state.json").write_text(
                json.dumps(
                    {
                        "workspace": tmpdir,
                        "run_dir": str(runs_dir / run_id),
                        "status": "PENDING",
                        "current_iteration": 0,
                        "max_iterations": 10,
                    }
                )
            )
        assert StateStorage.list_runs(tmpdir) == [
            "20240103_120000",
            "20240102_060000",
            "20240101_090000",
        ]


def test_list_runs_empty_workspace():
    """list_runs with no .rtw/runs returns []."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert StateStorage.list_runs(tmpdir) == []


def test_get_latest_run_returns_none_when_empty():
    """get_latest_run with no runs returns None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert StateStorage.get_latest_run(tmpdir) is None


def test_get_latest_run_returns_most_recent():
    """get_latest_run returns storage for newest run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for run_id in ["a", "b"]:
            s = StateStorage(tmpdir, run_id)
            s.save(SharedState(workspace=tmpdir, run_dir=str(s.base_dir)))
        latest = StateStorage.get_latest_run(tmpdir)
        assert latest is not None
        assert latest.run_id == "b"


def test_save_writes_iter_snapshot_when_subtask_passed():
    """When subtask_status is PASSED and iteration > 0, save writes history snapshot."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "snap")
        storage.initialize_task_doc("# Task")
        (storage.base_dir / "PLAN.md").write_text("# Plan")
        (storage.base_dir / "SUBTASK.md").write_text("# Subtask")
        state = SharedState(
            workspace=tmpdir,
            run_dir=str(storage.base_dir),
            current_iteration=1,
            subtask_status=SubtaskStatus.PASSED,
        )
        storage.save(state)
        assert (storage.history_dir / "iter-001_PLAN.md").exists()
        assert (storage.history_dir / "iter-001_SUBTASK.md").exists()
        assert not (storage.history_dir / "iter-001_TASK.md").exists()


def test_save_removes_subtask_when_summary_exists():
    """When SUMMARY.md exists, save() removes SUBTASK.md from run dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "done")
        storage.initialize_task_doc("# Task")
        (storage.base_dir / "SUBTASK.md").write_text("# Subtask")
        (storage.base_dir / "SUMMARY.md").write_text("# Summary")
        state = SharedState(
            workspace=tmpdir,
            run_dir=str(storage.base_dir),
        )
        storage.save(state)
        assert not storage.subtask_doc.exists()
        assert storage.summary_doc.exists()


def test_snapshot_omits_subtask_in_history_when_summary_exists():
    """When SUMMARY.md exists, iteration snapshot has SUMMARY in history but not SUBTASK."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StateStorage(tmpdir, "snap")
        storage.initialize_task_doc("# Task")
        (storage.base_dir / "PLAN.md").write_text("# Plan")
        (storage.base_dir / "SUBTASK.md").write_text("# Subtask")
        (storage.base_dir / "SUMMARY.md").write_text("# Summary")
        state = SharedState(
            workspace=tmpdir,
            run_dir=str(storage.base_dir),
            current_iteration=1,
            subtask_status=SubtaskStatus.PASSED,
        )
        storage.save(state)
        assert (storage.history_dir / "iter-001_PLAN.md").exists()
        assert (storage.history_dir / "iter-001_SUMMARY.md").exists()
        assert not (storage.history_dir / "iter-001_SUBTASK.md").exists()
        assert not storage.subtask_doc.exists()

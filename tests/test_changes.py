"""Change detection: SnapshotTracker, create_tracker, and binary-file safety."""

import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from rtw.architect.reviewer import read_changed_workspace_files
from rtw.core.changes import (
    GitTracker,
    SnapshotTracker,
    _is_inside_git_repo,
    _workspace_is_git_root,
    create_tracker,
)


def _git_init(workspace: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "-q", str(workspace)], check=True)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


class TestSnapshotTracker:
    def test_detects_added_file(self, workspace: Path):
        tracker = SnapshotTracker(workspace)
        tracker.snapshot()
        (workspace / "new.py").write_text("print('hi')")
        changes = tracker.changes()
        assert len(changes) == 1
        assert changes[0].path == "new.py"
        assert changes[0].action == "added"

    def test_detects_deleted_file(self, workspace: Path):
        f = workspace / "old.py"
        f.write_text("x = 1")
        tracker = SnapshotTracker(workspace)
        tracker.snapshot()
        f.unlink()
        changes = tracker.changes()
        assert len(changes) == 1
        assert changes[0].path == "old.py"
        assert changes[0].action == "deleted"

    def test_detects_modified_file(self, workspace: Path):
        f = workspace / "mod.py"
        f.write_text("x = 1")
        tracker = SnapshotTracker(workspace)
        tracker.snapshot()
        time.sleep(0.05)
        f.write_text("x = 2")
        changes = tracker.changes()
        assert len(changes) == 1
        assert changes[0].path == "mod.py"
        assert changes[0].action == "modified"

    def test_skips_rtw_directory(self, workspace: Path):
        tracker = SnapshotTracker(workspace)
        tracker.snapshot()
        rtw_dir = workspace / ".rtw"
        rtw_dir.mkdir()
        (rtw_dir / "state.json").write_text("{}")
        changes = tracker.changes()
        assert len(changes) == 0

    def test_skips_git_directory(self, workspace: Path):
        tracker = SnapshotTracker(workspace)
        tracker.snapshot()
        git_dir = workspace / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]")
        changes = tracker.changes()
        assert len(changes) == 0

    def test_no_changes_when_unchanged(self, workspace: Path):
        (workspace / "stable.py").write_text("pass")
        tracker = SnapshotTracker(workspace)
        tracker.snapshot()
        assert tracker.changes() == []


class TestCreateTracker:
    def test_returns_git_tracker_inside_git_repo(self, workspace: Path):
        _git_init(workspace)
        tracker = create_tracker(workspace)
        assert isinstance(tracker, GitTracker)

    def test_returns_snapshot_tracker_outside_git(self, workspace: Path):
        tracker = create_tracker(workspace)
        assert isinstance(tracker, SnapshotTracker)

    def test_returns_snapshot_tracker_in_subdirectory_of_repo(self, workspace: Path):
        """Subfolder of a repo: git paths are repo-relative, not workspace-relative (ISSUE #26)."""
        _git_init(workspace)
        subdir = workspace / "deep" / "nested"
        subdir.mkdir(parents=True)
        tracker = create_tracker(subdir)
        assert isinstance(tracker, SnapshotTracker)


class TestGitTrackerUntrackedFiles:
    def test_lists_nested_untracked_file_not_only_directory(self, workspace: Path):
        """--untracked-files=all yields file paths under new dirs (reviewer can load them)."""
        _git_init(workspace)
        git = shutil.which("git")
        assert git is not None
        (workspace / "root.py").write_text("x")
        subprocess.run([git, "-C", str(workspace), "add", "root.py"], check=True)
        subprocess.run([git, "-C", str(workspace), "commit", "-q", "-m", "init"], check=True)

        tracker = GitTracker(workspace)
        tracker.snapshot()
        nested = workspace / "pkg" / "nested.py"
        nested.parent.mkdir(parents=True)
        nested.write_text("y")
        changes = tracker.changes()
        paths = {c.path for c in changes}
        assert "pkg/nested.py" in paths or "pkg\\nested.py" in paths


class TestWorkspaceIsGitRoot:
    def test_true_at_repo_root(self, workspace: Path):
        _git_init(workspace)
        assert _workspace_is_git_root(workspace) is True

    def test_false_in_subdirectory(self, workspace: Path):
        _git_init(workspace)
        sub = workspace / "sub"
        sub.mkdir()
        assert _workspace_is_git_root(sub) is False


class TestIsInsideGitRepo:
    def test_true_at_git_root(self, workspace: Path):
        _git_init(workspace)
        assert _is_inside_git_repo(workspace) is True

    def test_true_in_subdirectory(self, workspace: Path):
        _git_init(workspace)
        sub = workspace / "sub"
        sub.mkdir()
        assert _is_inside_git_repo(sub) is True

    def test_false_outside_git(self, workspace: Path):
        assert _is_inside_git_repo(workspace) is False

    def test_false_on_subprocess_error(self, workspace: Path):
        with patch("rtw.core.changes.subprocess.run", side_effect=OSError("no git")):
            assert _is_inside_git_repo(workspace) is False


class TestReadChangedWorkspaceFiles:
    def test_reads_text_file(self, workspace: Path):
        (workspace / "app.py").write_text("print('hello')")
        result = read_changed_workspace_files(str(workspace), [{"path": "app.py"}])
        assert result["app.py"] == "print('hello')"

    def test_skips_binary_file_with_null_bytes(self, workspace: Path):
        (workspace / "data.bin").write_bytes(b"hello\x00world")
        result = read_changed_workspace_files(str(workspace), [{"path": "data.bin"}])
        assert result["data.bin"] == "(binary file)"

    def test_skips_missing_file(self, workspace: Path):
        result = read_changed_workspace_files(str(workspace), [{"path": "gone.py"}])
        assert "gone.py" not in result

    def test_skips_large_file(self, workspace: Path):
        (workspace / "huge.py").write_text("x" * 20000)
        result = read_changed_workspace_files(str(workspace), [{"path": "huge.py"}])
        assert "too large" in result["huge.py"]

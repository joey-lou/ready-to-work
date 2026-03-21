"""Change detection for executor outputs. Git-first, snapshot fallback."""

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

_SKIP_PREFIXES = (".rtw/", ".git/")


@dataclass
class FileChange:
    """Represents a detected file change."""

    path: str
    action: str  # "added", "modified", "deleted"


class ChangeTracker(ABC):
    """Base interface for detecting file changes in workspace."""

    @abstractmethod
    def snapshot(self) -> None:
        """Capture current state before agent runs."""

    @abstractmethod
    def changes(self) -> list[FileChange]:
        """Return detected changes after agent runs."""


class GitTracker(ChangeTracker):
    """Git-based change tracker using `git status --porcelain`."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._before: set[str] = set()

    def snapshot(self) -> None:
        """Capture git status before agent runs."""
        self._before = self._git_status_lines()

    def changes(self) -> list[FileChange]:
        """Detect changes by comparing git status snapshots."""
        after = self._git_status_lines()
        new_lines = sorted(after - self._before)
        result = []
        for line in new_lines:
            if len(line) < 4:
                continue
            status = line[:2]
            path = line[3:].strip()
            if path.startswith(_SKIP_PREFIXES):
                continue
            action = self._git_status_to_action(status)
            result.append(FileChange(path=path, action=action))
        return result

    def _git_status_lines(self) -> set[str]:
        """Run git status --porcelain and return set of output lines."""
        git = shutil.which("git")
        if not git:
            return set()
        try:
            result = subprocess.run(
                [
                    git,
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ],
                capture_output=True,
                text=True,
                cwd=str(self.workspace),
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                return set()
            return {line for line in result.stdout.splitlines() if line.strip()}
        except (OSError, subprocess.TimeoutExpired):
            return set()

    def _git_status_to_action(self, status: str) -> str:
        """Map git status code to action string."""
        if status.strip() in ("A", "??"):
            return "added"
        if status.strip() in ("D",):
            return "deleted"
        return "modified"


class SnapshotTracker(ChangeTracker):
    """Fallback change tracker using filesystem snapshots (mtime + size)."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._before: dict[str, tuple[float, int]] = {}

    def snapshot(self) -> None:
        """Capture filesystem state before agent runs."""
        self._before = self._scan_workspace()

    def changes(self) -> list[FileChange]:
        """Detect changes by comparing filesystem snapshots."""
        after = self._scan_workspace()
        result = []
        all_paths = set(self._before.keys()) | set(after.keys())
        for path in sorted(all_paths):
            if path.startswith(_SKIP_PREFIXES):
                continue
            before_stat = self._before.get(path)
            after_stat = after.get(path)
            if before_stat is None and after_stat is not None:
                result.append(FileChange(path=path, action="added"))
            elif before_stat is not None and after_stat is None:
                result.append(FileChange(path=path, action="deleted"))
            elif before_stat != after_stat:
                result.append(FileChange(path=path, action="modified"))
        return result

    def _scan_workspace(self) -> dict[str, tuple[float, int]]:
        """Walk workspace and return {rel_path: (mtime, size)} dict."""
        result = {}
        for root, _dirs, files in os.walk(self.workspace):
            root_path = Path(root)
            rel_root = root_path.relative_to(self.workspace)
            rel_root_str = str(rel_root)
            if any(rel_root_str.startswith(p.rstrip("/")) for p in _SKIP_PREFIXES):
                continue
            for filename in files:
                file_path = root_path / filename
                try:
                    stat = file_path.stat()
                    rel_path = str(file_path.relative_to(self.workspace))
                    result[rel_path] = (stat.st_mtime, stat.st_size)
                except OSError:
                    continue
        return result


def _is_inside_git_repo(workspace: Path) -> bool:
    """Check if workspace is inside any git repo (not just at the root)."""
    git = shutil.which("git")
    if not git:
        return False
    try:
        result = subprocess.run(
            [git, "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _workspace_is_git_root(workspace: Path) -> bool:
    """True when ``workspace`` is the repository root (paths match ``git status`` output)."""
    git = shutil.which("git")
    if not git:
        return False
    try:
        result = subprocess.run(
            [git, "rev-parse", "--show-prefix"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        return result.stdout.strip() == ""
    except (OSError, subprocess.TimeoutExpired):
        return False


def create_tracker(workspace: Path) -> ChangeTracker:
    """Factory: GitTracker only at repo root; else SnapshotTracker (correct paths in subfolders)."""
    if _is_inside_git_repo(workspace) and _workspace_is_git_root(workspace):
        return GitTracker(workspace)
    return SnapshotTracker(workspace)

"""Minimal state persistence. All context in run_dir .md files and state.json."""

import json
import logging
from datetime import datetime
from pathlib import Path
from shutil import copy2

from rtw.core.paths import PLAN_MD, SUBTASK_MD, SUMMARY_MD, TASK_MD
from rtw.core.state import SharedState, SubtaskStatus

logger = logging.getLogger(__name__)


class StateStorage:
    """
    Persists minimal SharedState to state.json. Agents update state.json (plan_status, subtask_status, blocking_reason).
    History: one snapshot per iteration (when reviewer passes), named iter-NNN.
    """

    def __init__(self, workspace: str | Path, run_id: str | None = None):
        self.workspace = Path(workspace)
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base_dir = self.workspace / ".rtw" / "runs" / self.run_id
        self.history_dir = self.base_dir / "history"
        self.tmp_dir = self.base_dir / "tmp"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state_file(self) -> Path:
        return self.base_dir / "state.json"

    @property
    def task_doc(self) -> Path:
        return self.base_dir / TASK_MD

    @property
    def plan_doc(self) -> Path:
        return self.base_dir / PLAN_MD

    @property
    def subtask_doc(self) -> Path:
        return self.base_dir / SUBTASK_MD

    @property
    def summary_doc(self) -> Path:
        return self.base_dir / SUMMARY_MD

    def initialize_task_doc(self, task_content: str) -> None:
        if not self.task_doc.exists():
            self.task_doc.write_text(task_content.strip() + "\n")

    def save(self, state: SharedState) -> None:
        state.touch()
        self.state_file.write_text(json.dumps(state.to_dict(), indent=2))
        logger.debug("State saved to %s", self.state_file)
        if state.subtask_status == SubtaskStatus.PASSED and state.current_iteration > 0:
            self._write_iteration_snapshot(state.current_iteration)
        if self.summary_doc.exists():
            self.subtask_doc.unlink(missing_ok=True)

    def _write_iteration_snapshot(self, iteration: int) -> None:
        prefix = f"iter-{iteration:03d}"
        self._copy_if_exists(self.plan_doc, self.history_dir / f"{prefix}_{PLAN_MD}")
        if not self.summary_doc.exists():
            self._copy_if_exists(self.subtask_doc, self.history_dir / f"{prefix}_{SUBTASK_MD}")
        self._copy_if_exists(self.summary_doc, self.history_dir / f"{prefix}_{SUMMARY_MD}")

    def _copy_if_exists(self, src: Path, dst: Path) -> None:
        if src.exists():
            copy2(src, dst)

    def load(self) -> SharedState | None:
        if not self.state_file.exists():
            return None
        try:
            data = json.loads(self.state_file.read_text())
            state = SharedState.from_dict(data)
            state.task_file = str(self.task_doc)
            if self.task_doc.exists():
                state.task_content = self.task_doc.read_text()
            return state
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error("Failed to load state: %s", e)
            return None

    @classmethod
    def list_runs(cls, workspace: str | Path) -> list[str]:
        runs_dir = Path(workspace) / ".rtw" / "runs"
        if not runs_dir.exists():
            return []
        return sorted(
            [
                d.name
                for d in runs_dir.iterdir()
                if d.is_dir() and (runs_dir / d.name / "state.json").is_file()
            ],
            reverse=True,
        )

    @classmethod
    def get_latest_run(cls, workspace: str | Path) -> "StateStorage | None":
        runs = cls.list_runs(workspace)
        if not runs:
            return None
        return cls(workspace, runs[0])

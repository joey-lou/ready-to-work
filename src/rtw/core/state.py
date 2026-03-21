"""Minimal machine state for the document-driven RTW loop. All context in .md and state.json."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


def _resolve_path_under_workspace(workspace: str, stored: str) -> str:
    """Resolve a path from state.json: relative paths are under workspace; absolute is legacy."""
    p = Path(stored)
    if p.is_absolute():
        return str(p.resolve())
    return str((Path(workspace).resolve() / p).resolve())


def _path_for_persist(workspace: str, path_str: str | None) -> str | None:
    """Store run_dir / run_tmp_dir workspace-relative when possible (portable state.json)."""
    if path_str is None:
        return None
    ws = Path(workspace).resolve()
    path = Path(path_str).resolve()
    try:
        return path.relative_to(ws).as_posix()
    except ValueError:
        return str(path)


class FlowStatus(Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class PlanStatus(Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class SubtaskStatus(Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REVISE = "REVISE"
    PASSED = "PASSED"
    BLOCKED = "BLOCKED"


@dataclass
class SharedState:
    """Minimal state for routing and resumability. Task/plan/subtask content live in .md files."""

    workspace: str
    run_dir: str
    run_tmp_dir: str | None = None

    status: FlowStatus = FlowStatus.PENDING
    plan_status: PlanStatus = PlanStatus.NOT_STARTED
    subtask_status: SubtaskStatus = SubtaskStatus.DRAFT
    current_iteration: int = 0
    max_iterations: int = 10
    blocking_reason: str | None = None
    files_changed: list[dict[str, str]] = field(default_factory=list)

    # Populated at run start or load from TASK.md; not persisted
    task_file: str = ""
    task_content: str = ""

    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "run_dir": _path_for_persist(self.workspace, self.run_dir),
            "run_tmp_dir": _path_for_persist(self.workspace, self.run_tmp_dir),
            "status": self.status.value,
            "plan_status": self.plan_status.value,
            "subtask_status": self.subtask_status.value,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "blocking_reason": self.blocking_reason,
            "files_changed": self.files_changed,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SharedState":
        ws = data["workspace"]
        run_dir = _resolve_path_under_workspace(ws, data["run_dir"])
        raw_tmp = data.get("run_tmp_dir")
        run_tmp = _resolve_path_under_workspace(ws, raw_tmp) if raw_tmp else None
        return cls(
            workspace=ws,
            run_dir=run_dir,
            run_tmp_dir=run_tmp,
            status=FlowStatus(data["status"]),
            plan_status=PlanStatus(data.get("plan_status", PlanStatus.NOT_STARTED.value)),
            subtask_status=SubtaskStatus(data.get("subtask_status", SubtaskStatus.DRAFT.value)),
            current_iteration=data["current_iteration"],
            max_iterations=data["max_iterations"],
            blocking_reason=data.get("blocking_reason"),
            files_changed=data.get("files_changed", []),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )

    def start_iteration(self) -> None:
        self.current_iteration += 1
        self.touch()

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat()

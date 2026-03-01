"""Minimal machine state for the document-driven RTW loop. All context in .md and state.json."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


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
            "run_dir": self.run_dir,
            "run_tmp_dir": self.run_tmp_dir,
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
        return cls(
            workspace=data["workspace"],
            run_dir=data["run_dir"],
            run_tmp_dir=data.get("run_tmp_dir"),
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

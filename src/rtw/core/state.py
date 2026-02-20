"""Shared state management for rtw architect loop."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class FlowStatus(Enum):
    PENDING = "pending"
    PLANNING = "planning"
    BUILDING = "building"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass
class Artifact:
    path: str
    action: str  # created, modified, deleted
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class IterationRecord:
    iteration: int
    plan: dict | None = None
    build_result: dict | None = None
    review_result: dict | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SharedState:
    """Central state object passed through the architect loop."""

    task_file: str
    task_content: str
    workspace: str

    status: FlowStatus = FlowStatus.PENDING
    current_iteration: int = 0
    max_iterations: int = 10

    current_plan: dict | None = None
    artifacts: list[Artifact] = field(default_factory=list)
    history: list[IterationRecord] = field(default_factory=list)

    blocking_reason: str | None = None
    final_summary: str | None = None

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_file": self.task_file,
            "task_content": self.task_content,
            "workspace": self.workspace,
            "status": self.status.value,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "current_plan": self.current_plan,
            "artifacts": [
                {"path": a.path, "action": a.action, "timestamp": a.timestamp}
                for a in self.artifacts
            ],
            "history": [
                {
                    "iteration": h.iteration,
                    "plan": h.plan,
                    "build_result": h.build_result,
                    "review_result": h.review_result,
                    "timestamp": h.timestamp,
                }
                for h in self.history
            ],
            "blocking_reason": self.blocking_reason,
            "final_summary": self.final_summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SharedState":
        state = cls(
            task_file=data["task_file"],
            task_content=data["task_content"],
            workspace=data["workspace"],
            status=FlowStatus(data["status"]),
            current_iteration=data["current_iteration"],
            max_iterations=data["max_iterations"],
            current_plan=data.get("current_plan"),
            blocking_reason=data.get("blocking_reason"),
            final_summary=data.get("final_summary"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )
        state.artifacts = [
            Artifact(
                path=a["path"],
                action=a["action"],
                timestamp=a.get("timestamp", datetime.now().isoformat()),
            )
            for a in data.get("artifacts", [])
        ]
        state.history = [
            IterationRecord(
                iteration=h["iteration"],
                plan=h.get("plan"),
                build_result=h.get("build_result"),
                review_result=h.get("review_result"),
                timestamp=h.get("timestamp", ""),
            )
            for h in data.get("history", [])
        ]
        return state

    def add_artifact(self, path: str, action: str) -> None:
        self.artifacts.append(Artifact(path=path, action=action))
        self.touch()

    def start_iteration(self) -> IterationRecord:
        self.current_iteration += 1
        record = IterationRecord(iteration=self.current_iteration)
        self.history.append(record)
        self.touch()
        return record

    def current_record(self) -> IterationRecord | None:
        return self.history[-1] if self.history else None

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat()

    def context_summary(self) -> str:
        """Generate context for LLM about current state."""
        lines = [
            f"Task: {self.task_file}",
            f"Iteration: {self.current_iteration}/{self.max_iterations}",
            f"Status: {self.status.value}",
        ]
        if self.artifacts:
            lines.append(f"Artifacts created: {len(self.artifacts)}")
        if self.current_plan:
            lines.append(f"Current plan steps: {len(self.current_plan.get('steps', []))}")
        return "\n".join(lines)

"""Shared state management for rtw architect loop."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

MAX_LESSONS = 50


class FlowStatus(Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
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
class LessonLearned:
    """A lesson learned during the architect loop."""

    iteration: int
    category: str  # "success", "failure", "insight", "review"
    description: str
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

    lessons_learned: list[LessonLearned] = field(default_factory=list)

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
            "lessons_learned": [
                {
                    "iteration": ll.iteration,
                    "category": ll.category,
                    "description": ll.description,
                    "timestamp": ll.timestamp,
                }
                for ll in self.lessons_learned
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
        state.lessons_learned = [
            LessonLearned(
                iteration=ll["iteration"],
                category=ll["category"],
                description=ll["description"],
                timestamp=ll.get("timestamp", datetime.now().isoformat()),
            )
            for ll in data.get("lessons_learned", [])
        ]
        return state

    def add_artifact(self, path: str, action: str) -> None:
        """Upsert artifact by path -- keeps the latest action per file."""
        for i, a in enumerate(self.artifacts):
            if a.path == path:
                self.artifacts[i] = Artifact(path=path, action=action)
                self.touch()
                return
        self.artifacts.append(Artifact(path=path, action=action))
        self.touch()

    def add_lesson(self, category: str, description: str) -> None:
        """Add a lesson learned, capping at MAX_LESSONS (oldest trimmed)."""
        self.lessons_learned.append(
            LessonLearned(
                iteration=self.current_iteration,
                category=category,
                description=description,
            )
        )
        if len(self.lessons_learned) > MAX_LESSONS:
            self.lessons_learned = self.lessons_learned[-MAX_LESSONS:]
        self.touch()

    def get_lessons_summary(self) -> str:
        """Generate a summary of all lessons learned for LLM context."""
        if not self.lessons_learned:
            return ""

        by_category: dict[str, list[str]] = {}
        for ll in self.lessons_learned:
            by_category.setdefault(ll.category, []).append(
                f"[iter {ll.iteration}] {ll.description}"
            )

        parts = ["## Lessons Learned from Previous Iterations\n"]
        for category, lessons in by_category.items():
            parts.append(f"### {category.replace('_', ' ').title()}")
            for lesson in lessons:
                parts.append(f"- {lesson}")
            parts.append("")

        return "\n".join(parts)

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

    def get_step_results(self, iteration: int | None = None) -> list[dict[str, Any]]:
        """Get step-level execution results for an iteration."""
        target_iter = iteration or self.current_iteration
        for record in self.history:
            if record.iteration == target_iter and record.build_result:
                return record.build_result.get("completed_steps", [])
        return []

    def get_failed_steps(self, iteration: int | None = None) -> list[dict[str, Any]]:
        """Get steps that failed in an iteration."""
        steps = self.get_step_results(iteration)
        return [s for s in steps if s.get("status") == "failed"]

    def get_execution_summary(self) -> str:
        """Summary of execution progress across all iterations."""
        total_completed = 0
        total_failed = 0
        total_duration = 0.0
        for record in self.history:
            if record.build_result:
                c, f, d = _aggregate_steps(record.build_result.get("completed_steps", []))
                total_completed += c
                total_failed += f
                total_duration += d
        return (
            f"Execution: {total_completed} steps completed, "
            f"{total_failed} failed across {len(self.history)} iterations "
            f"({total_duration:.1f}s total)"
        )


def _aggregate_steps(steps: list[dict[str, Any]]) -> tuple[int, int, float]:
    """Sum completed/failed counts and duration from a list of step dicts."""
    completed = sum(1 for s in steps if s.get("status") == "completed")
    failed = sum(1 for s in steps if s.get("status") == "failed")
    duration = sum(s.get("duration_seconds", 0) or 0 for s in steps)
    return completed, failed, duration

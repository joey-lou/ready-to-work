"""Base abstraction for coding agent backends.

Two-layer hierarchy:
- AgentBackend: lean ABC that any backend (subprocess, API, mock) can implement
- SubprocessAgentBackend: shared infrastructure for backends that wrap CLI tools
"""

import json
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1800  # 30 min per step


class StepStatus(Enum):
    """Status of a single execution step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FileChange:
    """A file modification made by the agent."""

    path: str
    action: str  # created, modified, deleted
    diff_summary: str | None = None


@dataclass
class StepResult:
    """Result of executing a single plan step."""

    step_id: int
    status: StepStatus
    description: str
    action_taken: str | None = None
    files_changed: list[FileChange] = field(default_factory=list)
    error: str | None = None
    agent_output: str | None = None
    duration_seconds: float | None = None


@dataclass
class AgentResult:
    """Result of an agent execution (may include multiple steps)."""

    success: bool
    steps: list[StepResult] = field(default_factory=list)
    summary: str | None = None
    raw_output: str | None = None
    error: str | None = None

    @property
    def files_changed(self) -> list[FileChange]:
        """All files changed across all steps."""
        changes = []
        for step in self.steps:
            changes.extend(step.files_changed)
        return changes

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    @property
    def completed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == StepStatus.COMPLETED]


class AgentError(RuntimeError):
    """Raised when agent execution fails."""

    def __init__(self, message: str, raw_output: str = ""):
        super().__init__(message)
        self.raw_output = raw_output


class AgentBackend(ABC):
    """Lean interface for coding agent backends.

    Any backend (subprocess-based, API-based, mock) implements these three
    methods. No subprocess assumptions leak into the interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this backend."""

    @abstractmethod
    def execute_step(
        self,
        step: dict[str, Any],
        workspace: Path,
        context: str | None = None,
    ) -> StepResult:
        """Execute a single plan step with full agent capabilities."""

    @abstractmethod
    def complete_json(
        self,
        prompt: str,
        system: str | None = None,
    ) -> dict[str, Any]:
        """Generate a JSON-structured completion (for planning/reviewing)."""

    def execute_steps(
        self,
        steps: list[dict[str, Any]],
        workspace: Path,
        context: str | None = None,
        on_step_complete: Callable[[StepResult], None] | None = None,
    ) -> AgentResult:
        """Execute multiple steps sequentially with early exit on critical failure."""
        results = []
        has_critical_failure = False

        for step in steps:
            if has_critical_failure:
                results.append(
                    StepResult(
                        step_id=step.get("id", 0),
                        status=StepStatus.SKIPPED,
                        description=step.get("description", ""),
                        error="Skipped due to earlier critical failure",
                    )
                )
                continue

            result = self.execute_step(step, workspace, context)
            results.append(result)

            if on_step_complete:
                on_step_complete(result)

            if result.status == StepStatus.FAILED:
                step_type = step.get("type", "")
                if step_type in ("create", "modify") and result.error:
                    has_critical_failure = True

        success = not has_critical_failure and all(
            r.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for r in results
        )

        return AgentResult(
            success=success,
            steps=results,
            summary=self._summarize_results(results),
        )

    def _summarize_results(self, results: list[StepResult]) -> str:
        completed = sum(1 for r in results if r.status == StepStatus.COMPLETED)
        failed = sum(1 for r in results if r.status == StepStatus.FAILED)
        skipped = sum(1 for r in results if r.status == StepStatus.SKIPPED)

        parts = [f"{completed} completed"]
        if failed:
            parts.append(f"{failed} failed")
        if skipped:
            parts.append(f"{skipped} skipped")

        return f"Steps: {', '.join(parts)}"


class SubprocessAgentBackend(AgentBackend):
    """Base class for backends that wrap CLI tools via subprocess.

    Subclasses only define CLI-specific command building and output parsing.
    Subprocess execution, JSON extraction, and timeouts are handled here.
    """

    def __init__(
        self,
        workspace: Path,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.workspace = Path(workspace)
        self.model = model
        self.timeout = timeout or int(os.environ.get("RTW_STEP_TIMEOUT", DEFAULT_TIMEOUT))

    @abstractmethod
    def _build_exec_command(self, prompt: str, workspace: Path) -> list[str]:
        """Build CLI command for step execution."""

    @abstractmethod
    def _build_json_command(self, prompt: str) -> list[str]:
        """Build CLI command for JSON completion."""

    @abstractmethod
    def _parse_exec_output(self, output: str, step_id: int, description: str) -> StepResult:
        """Parse execution output into StepResult."""

    @abstractmethod
    def _parse_json_output(self, output: str) -> dict[str, Any]:
        """Parse JSON output from agent."""

    def execute_step(
        self,
        step: dict[str, Any],
        workspace: Path,
        context: str | None = None,
    ) -> StepResult:
        step_id = step.get("id", 0)
        description = step.get("description", "Unknown step")

        prompt = self._build_step_prompt(step, context)
        cmd = self._build_exec_command(prompt, workspace)

        logger.info("Executing step %d: %s", step_id, description[:60])
        start_time = time.time()

        try:
            output = self._run_subprocess(cmd, workspace)
            duration = time.time() - start_time

            result = self._parse_exec_output(output, step_id, description)
            result.duration_seconds = duration
            result.agent_output = output[:2000] if output else None

            logger.info("Step %d %s (%.1fs)", step_id, result.status.value, duration)
            return result

        except AgentError as e:
            duration = time.time() - start_time
            logger.error("Step %d failed: %s", step_id, e)
            return StepResult(
                step_id=step_id,
                status=StepStatus.FAILED,
                description=description,
                error=str(e),
                agent_output=e.raw_output[:2000] if e.raw_output else None,
                duration_seconds=duration,
            )

    def complete_json(
        self,
        prompt: str,
        system: str | None = None,
    ) -> dict[str, Any]:
        full_prompt = self._build_json_prompt(prompt, system)
        cmd = self._build_json_command(full_prompt)

        logger.debug("Invoking %s for JSON completion", self.name)

        output = self._run_subprocess(cmd, self.workspace)
        return self._parse_json_output(output)

    def _run_subprocess(self, cmd: list[str], cwd: Path) -> str:
        """Run a subprocess and return stdout. Common error handling."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(cwd),
            )

            if result.returncode != 0:
                raise AgentError(f"{self.name} failed: {result.stderr}", result.stderr or "")

            return result.stdout.strip()

        except subprocess.TimeoutExpired as e:
            raise AgentError(f"{self.name} timed out after {self.timeout}s") from e
        except FileNotFoundError as e:
            raise AgentError(f"{self.name} CLI not found. Check installation.") from e

    def _build_step_prompt(self, step: dict[str, Any], context: str | None) -> str:
        step_id = step.get("id", "?")
        description = step.get("description", "")
        target = step.get("target", "")
        details = step.get("details", "")

        parts = [
            f"Execute step {step_id}: {description}",
            f"Target: {target}" if target else "",
            f"Details: {details}" if details else "",
            "",
            "Actually make the changes - don't just describe them.",
        ]

        if context:
            parts.extend(["", "Context:", context])

        return "\n".join(p for p in parts if p)

    def _build_json_prompt(self, prompt: str, system: str | None) -> str:
        parts = []
        if system:
            parts.append(f"<system>\n{system}\n</system>\n")
        parts.append(prompt)
        parts.append("\nRespond with valid JSON only. No markdown, no explanation.")
        return "\n".join(parts)

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from text, handling various formats."""
        if not text or not text.strip():
            raise AgentError("Empty response")

        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            candidate = text[first : last + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        raise AgentError(f"Failed to parse JSON: {text[:200]}", text)

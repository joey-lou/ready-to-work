"""Base abstraction for coding agent backends.

Agents are given workspace + full prompt (e.g. SUBTASK.md content) and execute once.
"""

import logging
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1800  # 30 min per run


@dataclass
class AgentResult:
    """Result of a single agent run."""

    success: bool
    output: str | None = None
    error: str | None = None


class AgentError(RuntimeError):
    """Raised when agent execution fails."""

    def __init__(self, message: str, raw_output: str = ""):
        super().__init__(message)
        self.raw_output = raw_output


class AgentBackend(ABC):
    """Interface for agent backends. Execute with workspace + full prompt."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this backend."""

    @abstractmethod
    def execute(
        self,
        workspace: Path,
        prompt: str,
        run_dir: Path | None = None,
    ) -> AgentResult:
        """Run the agent with the given prompt. Optional run_dir for context (e.g. where to write state)."""


class SubprocessAgentBackend(AgentBackend):
    """Base for backends that wrap CLI tools. Subclasses define command build and output parsing."""

    def __init__(
        self,
        workspace: Path,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.workspace = Path(workspace)
        self.model = model
        self.timeout = timeout or int(os.environ.get("RTW_AGENT_TIMEOUT", DEFAULT_TIMEOUT))

    @abstractmethod
    def _build_command(self, prompt: str, workspace: Path) -> list[str]:
        """Build CLI command for this prompt and workspace."""

    def _parse_output(self, output: str) -> AgentResult:
        """Parse raw stdout into AgentResult. Override in subclasses if needed."""
        return AgentResult(success=True, output=output or None)

    def execute(
        self,
        workspace: Path,
        prompt: str,
        run_dir: Path | None = None,
    ) -> AgentResult:
        cmd = self._build_command(prompt, workspace)
        logger.info("Running %s (timeout=%ds)", self.name, self.timeout)
        try:
            raw = self._run_subprocess(cmd, workspace)
            return self._parse_output(raw)
        except AgentError as e:
            logger.error("%s failed: %s", self.name, e)
            return AgentResult(
                success=False,
                output=e.raw_output[:2000] if e.raw_output else None,
                error=str(e),
            )

    def _run_subprocess(self, cmd: list[str], cwd: Path) -> str:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(cwd),
            )
            if result.returncode != 0:
                raise AgentError(
                    f"{self.name} failed: {result.stderr or 'non-zero exit'}",
                    result.stderr or result.stdout or "",
                )
            return (result.stdout or "").strip()
        except subprocess.TimeoutExpired as e:
            raise AgentError(f"{self.name} timed out after {self.timeout}s") from e
        except FileNotFoundError as e:
            raise AgentError(f"{self.name} CLI not found. Check installation.") from e

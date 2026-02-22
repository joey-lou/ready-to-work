"""Claude Code CLI backend for rtw.

Uses `claude` CLI to run tasks with full agent capabilities.
The agent can read files, write files, run commands, search code, etc.

CLI usage:
  claude -p "prompt" --output-format json --dangerously-skip-permissions
  claude -p "prompt" --output-format stream-json

See: https://docs.claude.com/en/docs/claude-code/cli-reference
"""

import json
import logging
from pathlib import Path
from typing import Any

from .base import AgentError, FileChange, StepResult, StepStatus, SubprocessAgentBackend

logger = logging.getLogger(__name__)


class ClaudeCodeBackend(SubprocessAgentBackend):
    """Agent backend using Claude Code CLI."""

    def __init__(
        self,
        workspace: Path,
        model: str | None = None,
        timeout: int | None = None,
    ):
        super().__init__(workspace, model, timeout)

    @property
    def name(self) -> str:
        return "claude"

    def _build_exec_command(self, prompt: str, workspace: Path) -> list[str]:
        """Build claude command for step execution."""
        cmd = [
            "claude",
            "-p",
            prompt,  # Print mode (non-interactive)
            "--output-format",
            "json",
            "--dangerously-skip-permissions",  # Auto-approve all actions
        ]
        return cmd

    def _build_json_command(self, prompt: str) -> list[str]:
        """Build claude command for JSON completion."""
        return self._build_exec_command(prompt, self.workspace)

    def _parse_exec_output(self, output: str, step_id: int, description: str) -> StepResult:
        """Parse claude JSON output into StepResult."""
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            # Fallback: assume success if we got any output
            return StepResult(
                step_id=step_id,
                status=StepStatus.COMPLETED,
                description=description,
                action_taken=output[:200] if output else "Completed",
            )

        # Handle error response
        if data.get("is_error") or data.get("error"):
            return StepResult(
                step_id=step_id,
                status=StepStatus.FAILED,
                description=description,
                error=data.get("error", data.get("result", "Unknown error")),
            )

        # Extract result text
        result_text = data.get("result", data.get("content", ""))

        # Extract file changes from structured output if available
        files_changed = []
        for f in data.get("files_changed", []):
            files_changed.append(
                FileChange(
                    path=f.get("path", ""),
                    action=f.get("action", "modified"),
                )
            )

        return StepResult(
            step_id=step_id,
            status=StepStatus.COMPLETED,
            description=description,
            action_taken=result_text[:200] if result_text else "Completed",
            files_changed=files_changed,
        )

    def _parse_json_output(self, output: str) -> dict[str, Any]:
        """Parse JSON from claude output."""
        try:
            data = json.loads(output)
            if data.get("is_error") or data.get("error"):
                raise AgentError(data.get("error", data.get("result", "Unknown error")), output)
            # The result/content field contains the actual response
            response_text = data.get("result", data.get("content", ""))
            return self._extract_json(response_text)
        except json.JSONDecodeError:
            # Try extracting JSON directly from output
            return self._extract_json(output)

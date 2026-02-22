"""Cursor Agent CLI backend for rtw.

Uses `cursor-agent` (or `agent`) CLI to execute tasks with full agent capabilities.
The agent can read files, write files, run commands, search code, etc.

CLI usage:
  cursor-agent -p "prompt" --output-format json --workspace /path
  agent -p "prompt" --output-format json --workspace /path
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from .base import AgentError, FileChange, StepResult, StepStatus, SubprocessAgentBackend

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sonnet-4.6"


def _find_cursor_cli() -> str:
    """Find the cursor agent CLI command."""
    for cmd in ("cursor-agent", "agent", "cursor"):
        if shutil.which(cmd):
            return cmd
    raise AgentError("Cursor CLI not found. Install from https://cursor.com")


class CursorAgentBackend(SubprocessAgentBackend):
    """Agent backend using Cursor Agent CLI."""

    def __init__(
        self,
        workspace: Path,
        model: str | None = None,
        timeout: int | None = None,
    ):
        super().__init__(workspace, model, timeout)
        self.model = model or DEFAULT_MODEL
        self._cli_cmd = _find_cursor_cli()

    @property
    def name(self) -> str:
        return "cursor"

    def _build_exec_command(self, prompt: str, workspace: Path) -> list[str]:
        """Build cursor-agent command for step execution."""
        cmd = [self._cli_cmd]

        # Handle 'cursor agent' vs 'cursor-agent' / 'agent'
        if self._cli_cmd == "cursor":
            cmd.append("agent")

        cmd.extend(
            [
                "-p",
                prompt,
                "--output-format",
                "json",
                "--model",
                self.model,
                "--workspace",
                str(workspace),
                "--force",
                "--trust",
            ]
        )
        return cmd

    def _build_json_command(self, prompt: str) -> list[str]:
        """Build cursor-agent command for JSON completion."""
        return self._build_exec_command(prompt, self.workspace)

    def _parse_exec_output(self, output: str, step_id: int, description: str) -> StepResult:
        """Parse cursor agent JSON output into StepResult."""
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
        if data.get("is_error"):
            return StepResult(
                step_id=step_id,
                status=StepStatus.FAILED,
                description=description,
                error=data.get("result", "Unknown error"),
            )

        # Extract result text
        result_text = data.get("result", "")

        # Extract file changes from structured output if available
        files_changed = []
        if "files_changed" in data:
            for f in data["files_changed"]:
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
        """Parse JSON from cursor agent output."""
        try:
            wrapper = json.loads(output)
            if wrapper.get("is_error"):
                raise AgentError(wrapper.get("result", "Unknown error"), output)
            # The result field contains the actual response
            response_text = wrapper.get("result", "")
            return self._extract_json(response_text)
        except json.JSONDecodeError:
            # Try extracting JSON directly from output
            return self._extract_json(output)

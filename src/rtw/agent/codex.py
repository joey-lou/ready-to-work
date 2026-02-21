"""OpenAI Codex CLI backend for rtw.

Uses `codex exec` to run non-interactive tasks with full agent capabilities.
The agent can read files, write files, run commands, search code, etc.

CLI usage:
  codex exec "prompt" --json --full-auto -C /path/to/workspace
  codex exec "prompt" -o output.txt --full-auto

See: https://developers.openai.com/codex/cli/reference/
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from .base import AgentBackend, FileChange, StepResult, StepStatus

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.3-codex"


class CodexAgentBackend(AgentBackend):
    """Agent backend using OpenAI Codex CLI."""

    def __init__(
        self,
        workspace: Path,
        model: str | None = None,
        timeout: int | None = None,
    ):
        super().__init__(workspace, model, timeout)
        self.model = model or os.environ.get("RTW_MODEL", DEFAULT_MODEL)

    @property
    def name(self) -> str:
        return "codex"

    def _build_exec_command(self, prompt: str, workspace: Path) -> list[str]:
        """Build codex exec command for step execution."""
        cmd = [
            "codex",
            "exec",
            prompt,
            "--json",  # Stream JSONL events
            "--full-auto",  # workspace-write sandbox, on-request approvals
            "-C",
            str(workspace),  # Set working directory
            "-m",
            self.model,
        ]
        return cmd

    def _build_json_command(self, prompt: str) -> list[str]:
        """Build codex exec command for JSON completion."""
        return self._build_exec_command(prompt, self.workspace)

    def _parse_exec_output(self, output: str, step_id: int, description: str) -> StepResult:
        """Parse codex JSONL output into StepResult.

        Codex --json outputs newline-delimited JSON events including:
        - turn.started, turn.completed, turn.failed
        - item.started, item.completed (for file changes, commands, etc.)
        """
        files_changed = []
        final_message = ""
        has_error = False
        error_msg = ""

        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            # Track file changes
            if event_type == "item.completed":
                item = event.get("item", {})
                item_type = item.get("type", "")

                if item_type == "file_edit":
                    files_changed.append(
                        FileChange(
                            path=item.get("path", ""),
                            action="modified",
                        )
                    )
                elif item_type == "file_create":
                    files_changed.append(
                        FileChange(
                            path=item.get("path", ""),
                            action="created",
                        )
                    )
                elif item_type == "file_delete":
                    files_changed.append(
                        FileChange(
                            path=item.get("path", ""),
                            action="deleted",
                        )
                    )
                elif item_type == "message":
                    final_message = item.get("content", "")[:200]

            # Track failures
            elif event_type == "turn.failed":
                has_error = True
                error_msg = event.get("error", {}).get("message", "Unknown error")

            elif event_type == "turn.completed":
                if not final_message:
                    final_message = "Completed"

        if has_error:
            return StepResult(
                step_id=step_id,
                status=StepStatus.FAILED,
                description=description,
                error=error_msg,
            )

        return StepResult(
            step_id=step_id,
            status=StepStatus.COMPLETED,
            description=description,
            action_taken=final_message or "Completed",
            files_changed=files_changed,
        )

    def _parse_json_output(self, output: str) -> dict[str, Any]:
        """Parse JSON from codex JSONL output.

        Look for the final message item which contains the JSON response.
        """
        for line in reversed(output.strip().split("\n")):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "item.completed":
                    item = event.get("item", {})
                    if item.get("type") == "message":
                        content = item.get("content", "")
                        return self._extract_json(content)
            except json.JSONDecodeError:
                continue

        # Fallback: try to extract JSON from the whole output
        return self._extract_json(output)

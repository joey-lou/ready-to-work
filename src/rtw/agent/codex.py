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
from pathlib import Path
from typing import Any

from .base import FileChange, StepResult, StepStatus, SubprocessAgentBackend

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.3-codex"

_ITEM_ACTION: dict[str, str] = {
    "file_edit": "modified",
    "file_create": "created",
    "file_delete": "deleted",
}


def _item_completed_to_changes(event: dict[str, Any]) -> tuple[list[FileChange], str | None]:
    """Convert item.completed event to file changes and optional message. Reduces branch count."""
    item = event.get("item", {})
    item_type = item.get("type", "")
    if item_type in _ITEM_ACTION:
        return [FileChange(path=item.get("path", ""), action=_ITEM_ACTION[item_type])], None
    if item_type == "message":
        return [], (item.get("content", "") or "")[:200]
    return [], None


def _parse_message_from_jsonl_line(line: str) -> str | None:
    """Parse a JSONL line; return message content if it is item.completed with type message."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if event.get("type") != "item.completed":
        return None
    item = event.get("item", {})
    if item.get("type") == "message":
        return item.get("content", "")
    return None


class CodexAgentBackend(SubprocessAgentBackend):
    """Agent backend using OpenAI Codex CLI."""

    def __init__(
        self,
        workspace: Path,
        model: str | None = None,
        timeout: int | None = None,
    ):
        super().__init__(workspace, model, timeout)
        self.model = model or DEFAULT_MODEL

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
            if event_type == "item.completed":
                extra_files, msg = _item_completed_to_changes(event)
                files_changed.extend(extra_files)
                if msg:
                    final_message = msg
            elif event_type == "turn.failed":
                has_error = True
                error_msg = event.get("error", {}).get("message", "Unknown error")
            elif event_type == "turn.completed" and not final_message:
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
            result = _parse_message_from_jsonl_line(line)
            if result is not None:
                return self._extract_json(result)
        return self._extract_json(output)

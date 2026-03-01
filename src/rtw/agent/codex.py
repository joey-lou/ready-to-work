"""OpenAI Codex CLI backend. Runs agent with workspace + full prompt."""

import json
import logging
from pathlib import Path

from .base import AgentResult, SubprocessAgentBackend

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.3-codex"


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

    def _build_command(self, prompt: str, workspace: Path) -> list[str]:
        return [
            "codex",
            "exec",
            prompt,
            "--json",
            "--full-auto",
            "-C",
            str(workspace),
            "-m",
            self.model,
        ]

    def _parse_output(self, output: str) -> AgentResult:
        """Parse codex JSONL output. Sets success=False on turn.failed."""
        has_error = False
        error_msg = ""
        final_message = ""

        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type", "")
            if event_type == "turn.failed":
                has_error = True
                error_msg = event.get("error", {}).get("message", "Unknown error")
            elif event_type == "turn.completed" and not final_message:
                final_message = "Completed"
            elif event_type == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "message":
                    final_message = (item.get("content") or "")[:500]

        if has_error:
            return AgentResult(success=False, output=output[:2000], error=error_msg)
        return AgentResult(success=True, output=final_message or output[:2000] or None)

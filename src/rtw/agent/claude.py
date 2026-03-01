"""Claude Code CLI backend. Runs agent with workspace + full prompt."""

import json
import logging
from pathlib import Path

from .base import AgentResult, SubprocessAgentBackend

logger = logging.getLogger(__name__)


class ClaudeCodeBackend(SubprocessAgentBackend):
    """Agent backend using Claude Code CLI."""

    @property
    def name(self) -> str:
        return "claude"

    def _build_command(self, prompt: str, workspace: Path) -> list[str]:
        return [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
        ]

    def _parse_output(self, output: str) -> AgentResult:
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return AgentResult(success=True, output=output[:2000] if output else None)
        if data.get("is_error") or data.get("error"):
            return AgentResult(
                success=False,
                output=output[:2000],
                error=str(data.get("error", data.get("result", "Unknown error"))),
            )
        result_text = data.get("result", data.get("content", ""))
        return AgentResult(success=True, output=(result_text or "")[:2000] or None)

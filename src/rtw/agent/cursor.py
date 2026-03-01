"""Cursor Agent CLI backend. Runs agent with workspace + full prompt."""

import logging
import shutil
from pathlib import Path

from .base import AgentError, SubprocessAgentBackend

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sonnet-4.6"


def _find_cursor_cli() -> str:
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

    def _build_command(self, prompt: str, workspace: Path) -> list[str]:
        cmd = [self._cli_cmd]
        if self._cli_cmd == "cursor":
            cmd.append("agent")
        cmd.extend(
            [
                "-p",
                prompt,
                "--model",
                self.model,
                "--workspace",
                str(workspace),
                "--force",
                "--trust",
            ]
        )
        return cmd

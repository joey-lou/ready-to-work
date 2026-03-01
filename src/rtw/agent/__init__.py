"""Agent backend abstraction for rtw.

Provides a swappable interface for CLI-based coding agents like:
- Cursor Agent (cursor-agent / agent)
- OpenAI Codex CLI (codex exec)
- Claude Code (claude -p)
"""

from .base import (
    AgentBackend,
    AgentError,
    AgentResult,
    SubprocessAgentBackend,
)
from .claude import ClaudeCodeBackend
from .codex import CodexAgentBackend
from .cursor import CursorAgentBackend

__all__ = [
    "AgentBackend",
    "AgentError",
    "AgentResult",
    "ClaudeCodeBackend",
    "CodexAgentBackend",
    "CursorAgentBackend",
    "SubprocessAgentBackend",
]

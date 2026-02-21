"""Agent backend abstraction for rtw.

Provides a swappable interface for CLI-based coding agents like:
- Cursor Agent (cursor-agent / agent)
- OpenAI Codex CLI (codex exec)
- Claude Code (claude -p)

The key abstraction: agents can EXECUTE tasks (with tool use, file ops)
not just DESCRIBE what they would do.
"""

from .base import (
    AgentBackend,
    AgentError,
    AgentResult,
    FileChange,
    StepResult,
    StepStatus,
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
    "FileChange",
    "StepResult",
    "StepStatus",
]

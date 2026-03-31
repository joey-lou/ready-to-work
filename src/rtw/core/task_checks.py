"""Optional TASK.md ## Checks: parse commands and run them for reviewer context."""

import re
import subprocess
from pathlib import Path

_CHECK_OUTPUT_CAP = 8000
_DEFAULT_TIMEOUT = 300


def parse_task_check_commands(task_markdown: str) -> list[str]:
    """Extract shell commands from a ``## Checks`` section (until the next ``##`` heading)."""
    if not task_markdown.strip():
        return []
    match = re.search(
        r"^##\s+Checks\s*\n(.*?)(?=^##\s|\Z)",
        task_markdown,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    block = match.group(1)
    commands: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        rest = line[2:].strip()
        full_tick = re.fullmatch(r"`([^`]+)`", rest)
        if full_tick:
            cmd = full_tick.group(1).strip()
            if cmd:
                commands.append(cmd)
            continue
        for piece in re.findall(r"`([^`]+)`", rest):
            piece = piece.strip()
            if piece:
                commands.append(piece)
    return commands


def run_task_check_commands(
    workspace: Path,
    commands: list[str],
    *,
    timeout: int = _DEFAULT_TIMEOUT,
) -> str:
    """Run each command with shell=True in ``workspace``; return a log for the reviewer prompt."""
    if not commands:
        return (
            "(No ## Checks section in TASK.md, or no bullet commands. "
            "Optional: add e.g.\n## Checks\n- `ruff check .`)"
        )
    lines: list[str] = []
    for i, cmd in enumerate(commands, start=1):
        lines.append(f"### Check {i}: {cmd}")
        try:
            result = subprocess.run(  # noqa: S602
                cmd,
                shell=True,  # TASK.md ## Checks may use pipes/redirection
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            combined = (result.stdout or "") + (result.stderr or "")
            if len(combined) > _CHECK_OUTPUT_CAP:
                combined = combined[:_CHECK_OUTPUT_CAP] + "\n... (truncated)"
            lines.append(f"exit code: {result.returncode}")
            lines.append(combined if combined.strip() else "(no output)")
        except subprocess.TimeoutExpired:
            lines.append(f"(timed out after {timeout}s)")
        except OSError as exc:
            lines.append(f"(error running command: {exc})")
    return "\n".join(lines)


def format_checks_for_prompt(workspace: Path, task_markdown: str) -> str:
    """Parse TASK.md checks and run them; safe no-op when section is absent."""
    cmds = parse_task_check_commands(task_markdown)
    if not cmds:
        return run_task_check_commands(workspace, [])
    return run_task_check_commands(workspace, cmds)

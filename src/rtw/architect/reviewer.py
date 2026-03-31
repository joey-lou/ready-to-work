"""Reviewer node: reviews against SUBTASK.md; updates subtask_status/blocking_reason in state.json."""

import logging
import os
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentError
from rtw.architect.prompts import REVIEWER
from rtw.core import FlowStatus, Node, SharedState, SubtaskStatus
from rtw.core.changes import workspace_path_is_skipped
from rtw.core.gatekeeper import retry_with_corrections, validate_reviewer_output
from rtw.core.io import read_json_dict, read_text_if_exists, relpath_or_abs
from rtw.core.paths import run_paths
from rtw.core.task_checks import format_checks_for_prompt
from rtw.core.trace import append_agent_trace

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10000
MAX_TOTAL_SIZE = 50000

_BINARY_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
    ".wasm",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".pyc",
    ".pyo",
    ".class",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".mov",
    ".sqlite",
    ".db",
)


def _walk_rel_prefix(rel_root: Path) -> str:
    return "" if rel_root == Path() else rel_root.as_posix()


def _collect_workspace_source_paths(ws: Path) -> list[Path]:
    candidates: list[Path] = []
    for root, dirs, files in os.walk(ws, topdown=True):
        rel_root = Path(root).relative_to(ws)
        rel_prefix = _walk_rel_prefix(rel_root)
        dirs[:] = [
            d
            for d in dirs
            if not workspace_path_is_skipped(f"{rel_prefix}/{d}" if rel_prefix else d)
        ]
        for name in files:
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            if workspace_path_is_skipped(rel):
                continue
            low = name.lower()
            if any(low.endswith(suf) for suf in _BINARY_SUFFIXES):
                continue
            candidates.append(Path(root) / name)
    return sorted(candidates, key=lambda p: p.as_posix())


def _fill_workspace_file_contents(ws: Path, candidates: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    total = 0
    for path in candidates:
        rel_key = path.relative_to(ws).as_posix()
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            out[rel_key] = f"(error: {exc})"
            continue
        if size > MAX_FILE_SIZE:
            out[rel_key] = f"(file too large: {size} bytes)"
            continue
        if total + size > MAX_TOTAL_SIZE:
            out[rel_key] = "(skipped: limit reached)"
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            out[rel_key] = f"(error: {exc})"
            continue
        if "\x00" in text:
            out[rel_key] = "(binary file)"
            continue
        out[rel_key] = text
        total += size
    return out


def read_workspace_source_files(workspace: str) -> dict[str, str]:
    """Load text contents of workspace source files (size-limited), excluding artifacts."""
    ws = Path(workspace)
    return _fill_workspace_file_contents(ws, _collect_workspace_source_paths(ws))


def read_changed_workspace_files(workspace: str, changed: list[dict]) -> dict[str, str]:
    """Load contents of changed files under workspace (size-limited)."""
    out: dict[str, str] = {}
    total = 0
    for item in changed:
        p = Path(workspace) / item.get("path", "")
        if not p.exists() or not p.is_file():
            continue
        try:
            size = p.stat().st_size
            if size > MAX_FILE_SIZE:
                out[item.get("path", "")] = f"(file too large: {size} bytes)"
                continue
            if total + size > MAX_TOTAL_SIZE:
                out[item.get("path", "")] = "(skipped: limit reached)"
                continue
            text = p.read_text(errors="replace")
            if "\x00" in text:
                out[item.get("path", "")] = "(binary file)"
                continue
            out[item.get("path", "")] = text
            total += size
        except OSError as e:
            out[item.get("path", "")] = f"(error: {e})"
    return out


def _build_reviewer_prompt(  # noqa: PLR0913
    workspace: Path,
    run_dir: Path,
    task: str,
    plan: str,
    subtask: str,
    files_changed: list[dict],
    file_contents: dict[str, str],
    lint_block: str,
    iteration: int,
    max_iter: int,
) -> str:
    changed_paths = "\n".join(f"- {c.get('path', '')}" for c in files_changed)
    file_contents_block = "\n\n".join(
        f"## {path}\n```\n{content}\n```" for path, content in file_contents.items()
    )
    return REVIEWER.format(
        run_dir_rel=relpath_or_abs(run_dir, workspace),
        task=task,
        plan=plan or "(none)",
        subtask=subtask or "(none)",
        changed_paths=changed_paths or "(none)",
        lint_block=lint_block or "(none)",
        file_contents_block=file_contents_block or "(no files)",
        iteration=iteration,
        max_iter=max_iter,
    )


class ReviewerNode(Node):
    def __init__(self, agent: AgentBackend):
        super().__init__("Reviewer")
        self.agent = agent

    def prep(self, state: SharedState) -> dict[str, Any]:
        state.status = FlowStatus.REVIEWING
        paths = run_paths(state.run_dir)
        changed_files = state.files_changed
        task_text = read_text_if_exists(paths["TASK"])
        ws = Path(state.workspace)

        return {
            "workspace": ws,
            "run_dir": Path(state.run_dir),
            "paths": paths,
            "task": task_text,
            "plan": read_text_if_exists(paths["PLAN"]),
            "subtask": read_text_if_exists(paths["SUBTASK"]),
            "files_changed": changed_files,
            "lint_block": format_checks_for_prompt(ws, task_text),
            "file_contents": read_workspace_source_files(state.workspace),
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
        }

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        run_dir = context["run_dir"]
        full_prompt = _build_reviewer_prompt(
            context["workspace"],
            run_dir,
            context["task"],
            context["plan"],
            context["subtask"],
            context["files_changed"],
            context["file_contents"],
            context["lint_block"],
            context["iteration"],
            context["max_iterations"],
        )
        logger.info("Reviewing iteration %d", context["iteration"])
        try:
            result = self.agent.execute(context["workspace"], full_prompt, run_dir=run_dir)
            return {
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "prompt": full_prompt,
            }
        except AgentError as exc:
            logger.error("Review failed: %s", exc)
            raise

    def post(
        self, state: SharedState, prep_result: dict[str, Any], exec_result: dict[str, Any]
    ) -> str | None:
        paths = run_paths(state.run_dir)

        append_agent_trace(
            state.run_dir,
            stage="REVIEWER",
            iteration=state.current_iteration,
            prompt=exec_result.get("prompt"),
            output=exec_result.get("output"),
        )

        gate_result = validate_reviewer_output(Path(state.run_dir))
        if not gate_result.passed:
            logger.warning("Reviewer output validation failed: %d issues", len(gate_result.issues))
            for issue in gate_result.issues:
                logger.warning("  %s [%s]: %s", issue.document, issue.level, issue.message)
            retry_with_corrections(
                self.agent,
                Path(state.workspace),
                Path(state.run_dir),
                gate_result.issues,
                validate=validate_reviewer_output,
            )

        data = read_json_dict(paths["state_file"])
        decision = str(data.get("subtask_status", "REVISE")).strip().upper()
        if not exec_result.get("success", True):
            decision = "BLOCKED"

        if decision == "BLOCKED":
            state.status = FlowStatus.BLOCKED
            state.subtask_status = SubtaskStatus.BLOCKED
            state.blocking_reason = str(data.get("blocking_reason") or "Reviewer marked blocked")
            state.touch()
            return None

        if decision == "PASSED":
            state.subtask_status = SubtaskStatus.PASSED
            state.status = FlowStatus.PENDING
            state.touch()
            return "plan"

        state.subtask_status = SubtaskStatus.REVISE
        state.status = FlowStatus.PENDING
        state.touch()
        return "execute"

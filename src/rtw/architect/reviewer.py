"""Reviewer node: reviews against SUBTASK.md; updates subtask_status/blocking_reason in state.json."""

import json
import logging
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentError
from rtw.architect.prompts import REVIEWER
from rtw.core import FlowStatus, Node, SharedState, SubtaskStatus
from rtw.core.paths import STATE_JSON, SUBTASK_MD, run_paths
from rtw.core.trace import append_agent_trace

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10000
MAX_TOTAL_SIZE = 50000


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _build_reviewer_prompt(  # noqa: PLR0913
    run_dir: Path,
    task: str,
    plan: str,
    subtask: str,
    files_changed: list[dict],
    file_contents: dict[str, str],
    iteration: int,
    max_iter: int,
) -> str:
    changed_paths = "\n".join(f"- {c.get('path', '')}" for c in files_changed)
    file_contents_block = "\n\n".join(
        f"## {path}\n```\n{content}\n```" for path, content in file_contents.items()
    )
    return REVIEWER.format(
        state_path=run_dir / STATE_JSON,
        task=task,
        plan=plan or "(none)",
        subtask=subtask or "(none)",
        changed_paths=changed_paths,
        file_contents_block=file_contents_block or "(no files)",
        iteration=iteration,
        max_iter=max_iter,
        subtask_path=run_dir / SUBTASK_MD,
    )


class ReviewerNode(Node):
    def __init__(self, agent: AgentBackend):
        super().__init__("Reviewer")
        self.agent = agent

    def prep(self, state: SharedState) -> dict[str, Any]:
        state.status = FlowStatus.REVIEWING
        paths = run_paths(state.run_dir)
        changed_files = state.files_changed

        return {
            "workspace": Path(state.workspace),
            "run_dir": Path(state.run_dir),
            "paths": paths,
            "task": _read(paths["TASK"]),
            "plan": _read(paths["PLAN"]),
            "subtask": _read(paths["SUBTASK"]),
            "files_changed": changed_files,
            "file_contents": self._read_changed(state.workspace, changed_files),
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
        }

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        run_dir = context["run_dir"]
        full_prompt = _build_reviewer_prompt(
            run_dir,
            context["task"],
            context["plan"],
            context["subtask"],
            context["files_changed"],
            context["file_contents"],
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
        data = _read_state(paths["state_file"])

        append_agent_trace(
            state.run_dir,
            stage="REVIEWER",
            iteration=state.current_iteration,
            prompt=exec_result.get("prompt"),
            output=exec_result.get("output"),
        )

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

    def _read_changed(self, workspace: str, changed: list[dict]) -> dict[str, str]:
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
                out[item.get("path", "")] = p.read_text(errors="replace")
                total += size
            except OSError as e:
                out[item.get("path", "")] = f"(error: {e})"
        return out

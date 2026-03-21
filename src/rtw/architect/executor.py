"""Executor node: runs SUBTASK.md; sets state.files_changed for reviewer."""

import logging
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentError
from rtw.architect.prompts import EXECUTOR
from rtw.core import FlowStatus, Node, SharedState, SubtaskStatus
from rtw.core.changes import create_tracker
from rtw.core.io import relpath_or_abs
from rtw.core.paths import run_paths
from rtw.core.trace import append_agent_trace

logger = logging.getLogger(__name__)


class ExecutorNode(Node):
    def __init__(self, agent: AgentBackend):
        super().__init__("Executor")
        self.agent = agent

    def prep(self, state: SharedState) -> dict[str, Any]:
        state.status = FlowStatus.EXECUTING
        paths = run_paths(state.run_dir)
        subtask_path = paths["SUBTASK"]

        tracker = create_tracker(Path(state.workspace))
        tracker.snapshot()

        return {
            "workspace": Path(state.workspace),
            "run_dir": Path(state.run_dir),
            "run_tmp_dir": state.run_tmp_dir,
            "paths": paths,
            "subtask_path": subtask_path,
            "subtask_markdown": subtask_path.read_text() if subtask_path.exists() else "",
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
            "tracker": tracker,
        }

    def exec(self, prep_result: dict[str, Any]) -> dict[str, Any]:
        prompt = _build_executor_prompt(prep_result)
        logger.info("Executing subtask iteration %d", prep_result["iteration"])
        try:
            result = self.agent.execute(
                prep_result["workspace"],
                prompt,
                run_dir=prep_result["run_dir"],
            )
            return {
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "prompt": prompt,
            }
        except AgentError as exc:
            logger.error("Executor failed: %s", exc)
            raise

    def post(
        self, state: SharedState, prep_result: dict[str, Any], exec_result: dict[str, Any]
    ) -> str:
        tracker = prep_result["tracker"]
        changes = tracker.changes()
        state.files_changed = [{"path": c.path, "action": c.action} for c in changes]

        append_agent_trace(
            state.run_dir,
            stage="EXECUTOR",
            iteration=state.current_iteration,
            prompt=exec_result.get("prompt"),
            output=exec_result.get("output"),
        )

        ok = exec_result.get("success", False)
        if not ok:
            state.subtask_status = SubtaskStatus.BLOCKED
            state.status = FlowStatus.BLOCKED
            state.blocking_reason = str(exec_result.get("error") or "Executor reported failure")
            state.touch()
            return None
        state.subtask_status = SubtaskStatus.NEEDS_REVIEW
        state.status = FlowStatus.PENDING
        state.touch()
        return "review"


def _build_executor_prompt(prep_result: dict[str, Any]) -> str:
    tmp_dir = prep_result.get("run_tmp_dir") or prep_result["run_dir"] / "tmp"
    tmp_dir_rel = relpath_or_abs(Path(tmp_dir), prep_result["workspace"])
    return EXECUTOR.format(
        tmp_dir_rel=tmp_dir_rel,
        subtask_markdown=prep_result["subtask_markdown"],
    )

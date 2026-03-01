"""Executor node: runs SUBTASK.md; sets state.files_changed for reviewer."""

import logging
import subprocess
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentResult
from rtw.architect.prompts import EXECUTOR
from rtw.core import FlowStatus, Node, SharedState, SubtaskStatus
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
        return {
            "workspace": Path(state.workspace),
            "run_dir": Path(state.run_dir),
            "run_tmp_dir": state.run_tmp_dir,
            "paths": paths,
            "subtask_path": subtask_path,
            "subtask_markdown": subtask_path.read_text() if subtask_path.exists() else "",
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
            "git_before": _git_status_lines(Path(state.workspace)),
        }

    def exec(self, prep_result: dict[str, Any]) -> AgentResult:
        prompt = _build_executor_prompt(prep_result)
        logger.info("Executing subtask iteration %d", prep_result["iteration"])
        return self.agent.execute(
            prep_result["workspace"],
            prompt,
            run_dir=prep_result["run_dir"],
        )

    def post(
        self, state: SharedState, prep_result: dict[str, Any], exec_result: AgentResult
    ) -> str:
        changed = _git_changed_paths(
            prep_result["git_before"],
            _git_status_lines(prep_result["workspace"]),
        )
        state.files_changed = [{"path": p, "action": "modified"} for p in changed]

        append_agent_trace(
            state.run_dir,
            stage="EXECUTOR",
            iteration=state.current_iteration,
            prompt=_build_executor_prompt(prep_result),
            output=exec_result.output,
        )

        state.subtask_status = (
            SubtaskStatus.NEEDS_REVIEW if exec_result.success else SubtaskStatus.BLOCKED
        )
        state.status = FlowStatus.PENDING
        state.touch()
        return "review"


def _git_status_lines(workspace: Path) -> set[str]:
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=str(workspace),
            check=False,
        )
    except OSError:
        return set()
    return (
        {line for line in (r.stdout or "").splitlines() if line.strip()}
        if r.returncode == 0
        else set()
    )


def _git_changed_paths(before: set[str], after: set[str]) -> list[str]:
    paths = []
    for line in sorted(after - before):
        if len(line) >= 4:
            paths.append(line[3:].strip())
    return paths


def _build_executor_prompt(prep_result: dict[str, Any]) -> str:
    tmp_dir = prep_result.get("run_tmp_dir") or prep_result["run_dir"] / "tmp"
    return EXECUTOR.format(
        workspace_path=prep_result["workspace"],
        tmp_dir=tmp_dir,
        subtask_markdown=prep_result["subtask_markdown"],
    )

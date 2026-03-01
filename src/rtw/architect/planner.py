"""Planner node: maintains PLAN.md, SUBTASK.md; updates plan_status/blocking_reason in state.json."""

import json
import logging
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentError
from rtw.architect.prompts import PLANNER
from rtw.core import FlowStatus, Node, PlanStatus, SharedState, SubtaskStatus
from rtw.core.paths import PLAN_MD, STATE_JSON, SUBTASK_MD, run_paths
from rtw.core.trace import append_agent_trace

logger = logging.getLogger(__name__)


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_plan_status(value: str | None) -> PlanStatus:
    if not value:
        return PlanStatus.IN_PROGRESS
    try:
        return PlanStatus(value)
    except ValueError:
        return PlanStatus.IN_PROGRESS


def _build_planner_prompt(
    run_dir: Path, task: str, plan: str, subtask: str, iteration: int, max_iter: int
) -> str:
    return PLANNER.format(
        state_path=run_dir / STATE_JSON,
        task=task,
        plan=plan or "(none yet)",
        subtask=subtask or "(none yet)",
        iteration=iteration,
        max_iter=max_iter,
        plan_path=run_dir / PLAN_MD,
        subtask_path=run_dir / SUBTASK_MD,
    )


class PlannerNode(Node):
    def __init__(self, agent: AgentBackend):
        super().__init__("Planner")
        self.agent = agent

    def prep(self, state: SharedState) -> dict[str, Any]:
        state.status = FlowStatus.PLANNING
        state.start_iteration()
        paths = run_paths(state.run_dir)
        return {
            "workspace": Path(state.workspace),
            "run_dir": Path(state.run_dir),
            "paths": paths,
            "task": _read(paths["TASK"]),
            "plan": _read(paths["PLAN"]),
            "subtask": _read(paths["SUBTASK"]),
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
        }

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        run_dir = context["run_dir"]
        full_prompt = _build_planner_prompt(
            run_dir,
            context["task"],
            context["plan"],
            context["subtask"],
            context["iteration"],
            context["max_iterations"],
        )
        logger.info("Planning iteration %d", context["iteration"])
        try:
            result = self.agent.execute(context["workspace"], full_prompt, run_dir=run_dir)
            return {
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "prompt": full_prompt,
            }
        except AgentError as exc:
            logger.error("Planner failed: %s", exc)
            raise

    def post(
        self, state: SharedState, prep_result: dict[str, Any], exec_result: dict[str, Any]
    ) -> str | None:
        paths = run_paths(state.run_dir)
        data = _read_state(paths["state_file"])
        plan_status = _safe_plan_status(data.get("plan_status"))

        append_agent_trace(
            state.run_dir,
            stage="PLANNER",
            iteration=state.current_iteration,
            prompt=exec_result.get("prompt"),
            output=exec_result.get("output"),
        )

        state.plan_status = plan_status
        state.subtask_status = SubtaskStatus.IN_PROGRESS

        if plan_status == PlanStatus.COMPLETED:
            state.status = FlowStatus.COMPLETED
            state.subtask_status = SubtaskStatus.PASSED
            state.touch()
            return None

        if plan_status == PlanStatus.BLOCKED:
            state.status = FlowStatus.BLOCKED
            state.blocking_reason = str(data.get("blocking_reason") or "Planner blocked")
            state.touch()
            return None

        state.status = FlowStatus.PENDING
        state.touch()
        return "execute"

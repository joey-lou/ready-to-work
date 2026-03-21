"""Planner node: maintains PLAN.md, SUBTASK.md; updates plan_status/blocking_reason in state.json."""

import logging
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentError
from rtw.architect.prompts import PLANNER
from rtw.core import FlowStatus, Node, PlanStatus, SharedState, SubtaskStatus
from rtw.core.gatekeeper import retry_with_corrections, validate_planner_output
from rtw.core.io import read_json_dict, read_text_if_exists, relpath_or_abs
from rtw.core.paths import run_paths
from rtw.core.trace import append_agent_trace

logger = logging.getLogger(__name__)


def _safe_plan_status(value: str | None) -> PlanStatus:
    if not value:
        return PlanStatus.IN_PROGRESS
    try:
        return PlanStatus(value)
    except ValueError:
        return PlanStatus.IN_PROGRESS


def _build_planner_prompt(  # noqa: PLR0913
    workspace: Path,
    run_dir: Path,
    task: str,
    plan: str,
    subtask: str,
    iteration: int,
    max_iter: int,
) -> str:
    return PLANNER.format(
        run_dir_rel=relpath_or_abs(run_dir, workspace),
        tmp_dir_rel=relpath_or_abs(run_dir / "tmp", workspace),
        task=task,
        plan=plan or "(none yet)",
        subtask=subtask or "(none yet)",
        iteration=iteration,
        max_iter=max_iter,
    )


class PlannerNode(Node):
    def __init__(self, agent: AgentBackend):
        super().__init__("Planner")
        self.increments_iteration = True
        self.agent = agent

    def prep(self, state: SharedState) -> dict[str, Any]:
        state.status = FlowStatus.PLANNING
        paths = run_paths(state.run_dir)
        return {
            "workspace": Path(state.workspace),
            "run_dir": Path(state.run_dir),
            "paths": paths,
            "task": read_text_if_exists(paths["TASK"]),
            "plan": read_text_if_exists(paths["PLAN"]),
            "subtask": read_text_if_exists(paths["SUBTASK"]),
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
        }

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        run_dir = context["run_dir"]
        full_prompt = _build_planner_prompt(
            context["workspace"],
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

        append_agent_trace(
            state.run_dir,
            stage="PLANNER",
            iteration=state.current_iteration,
            prompt=exec_result.get("prompt"),
            output=exec_result.get("output"),
        )

        gate_result = validate_planner_output(Path(state.run_dir))
        if not gate_result.passed:
            logger.warning("Planner output validation failed: %d issues", len(gate_result.issues))
            for issue in gate_result.issues:
                logger.warning("  %s [%s]: %s", issue.document, issue.level, issue.message)
            retry_with_corrections(
                self.agent,
                Path(state.workspace),
                Path(state.run_dir),
                gate_result.issues,
                validate=validate_planner_output,
            )

        data = read_json_dict(paths["state_file"])
        plan_status = _safe_plan_status(data.get("plan_status"))
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

"""Executor node for rtw architect loop.

Replaces the old Builder node with step-by-step execution using an agent backend.
The key difference: the agent ACTUALLY DOES the work (file ops, commands)
rather than describing what it would do.
"""

import logging
import os
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentResult, StepResult, StepStatus
from rtw.core import FlowStatus, Node, SharedState

logger = logging.getLogger(__name__)

MAX_STEPS_PER_ITERATION = int(os.environ.get("RTW_MAX_STEPS_PER_ITERATION", "5"))


class ExecutorNode(Node):
    """
    Executes plan steps using an agent backend with full tool capabilities.

    Unlike the old Builder which asked an LLM to describe what it would do,
    the Executor uses an agent that can actually:
    - Read and write files
    - Run shell commands
    - Search the codebase
    - Verify changes

    Execution is step-by-step with feedback between steps, allowing:
    - Early abort on critical failures
    - Progress tracking per step
    - Better error attribution
    """

    def __init__(self, agent: AgentBackend):
        super().__init__("Executor")
        self.agent = agent

    def prep(self, state: SharedState) -> dict[str, Any]:
        """Prepare execution context from current plan."""
        state.status = FlowStatus.EXECUTING

        # Get steps to execute this iteration
        plan = state.current_plan or {}
        all_steps = plan.get("steps", [])
        steps_to_run = all_steps[:MAX_STEPS_PER_ITERATION]

        # Build context for the agent
        context_parts = [
            f"Workspace: {state.workspace}",
            f"Iteration: {state.current_iteration} of {state.max_iterations}",
        ]
        if state.run_tmp_dir:
            context_parts.append(
                f"Temporary/scratch files must be created only under: {state.run_tmp_dir}"
            )

        if state.artifacts:
            context_parts.append(
                f"Existing files: {', '.join(a.path for a in state.artifacts[:10])}"
            )

        lessons = state.get_lessons_summary()
        if lessons:
            context_parts.append(f"\n{lessons}")

        return {
            "steps": steps_to_run,
            "all_steps_count": len(all_steps),
            "workspace": Path(state.workspace),
            "context": "\n".join(context_parts),
            "plan_summary": plan.get("summary", ""),
        }

    def exec(self, prep_result: dict[str, Any]) -> AgentResult:
        """Execute steps using the agent backend."""
        steps = prep_result["steps"]
        workspace = prep_result["workspace"]
        context = prep_result["context"]

        if not steps:
            logger.warning("No steps to execute")
            return AgentResult(
                success=True,
                summary="No steps in plan",
            )

        logger.info(
            "Executing %d of %d steps: %s",
            len(steps),
            prep_result["all_steps_count"],
            prep_result["plan_summary"][:60],
        )

        def on_step_complete(result: StepResult) -> None:
            status_emoji = "✓" if result.status == StepStatus.COMPLETED else "✗"
            logger.info(
                "  %s Step %d: %s",
                status_emoji,
                result.step_id,
                result.description[:50],
            )

        return self.agent.execute_steps(
            steps=steps,
            workspace=workspace,
            context=context,
            on_step_complete=on_step_complete,
        )

    def post(
        self, state: SharedState, prep_result: dict[str, Any], exec_result: AgentResult
    ) -> str:
        """Record execution results and transition to review."""
        record = state.current_record()

        # Convert AgentResult to the format expected by state/reviewer
        build_result = self._convert_to_build_result(exec_result)

        if record:
            record.build_result = build_result

        # Track artifacts from actual file changes
        for change in exec_result.files_changed:
            state.add_artifact(change.path, change.action)

        # Capture lessons from failures
        for step in exec_result.failed_steps:
            if step.error:
                state.add_lesson("failure", f"Step {step.step_id} failed: {step.error}")

        # Capture successful approaches
        for step in exec_result.completed_steps:
            if step.action_taken and len(step.files_changed) > 0:
                state.add_lesson(
                    "success",
                    f"Step {step.step_id}: {step.action_taken[:100]}",
                )

        state.touch()

        # Log summary
        logger.info(
            "Execution complete: %d completed, %d failed",
            len(exec_result.completed_steps),
            len(exec_result.failed_steps),
        )

        return "review"

    def _convert_to_build_result(self, result: AgentResult) -> dict[str, Any]:
        """Convert AgentResult to legacy build_result format for compatibility."""
        completed_steps = []
        for step in result.steps:
            completed_steps.append(
                {
                    "step_id": step.step_id,
                    "status": step.status.value,
                    "action_taken": step.action_taken,
                    "files_affected": [fc.path for fc in step.files_changed],
                    "notes": step.error or "",
                    "duration_seconds": step.duration_seconds,
                }
            )

        artifacts_created = [{"path": fc.path, "action": fc.action} for fc in result.files_changed]

        issues = [step.error for step in result.failed_steps if step.error]

        return {
            "completed_steps": completed_steps,
            "artifacts_created": artifacts_created,
            "issues_encountered": issues,
            "summary": result.summary,
            "success": result.success,
        }

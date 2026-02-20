"""Builder node for rtw architect loop."""

import logging
import os
from typing import Any

from rtw.core import FlowStatus, Node, SharedState
from rtw.llm import LLMClient, LLMResponseError

logger = logging.getLogger(__name__)

MAX_STEPS_PER_BUILD = int(os.environ.get("RTW_MAX_STEPS_PER_BUILD", "5"))

BUILDER_SYSTEM = """You are a senior software developer implementing a plan.
Execute each step precisely and report what was done. Execute only the steps listed below; remaining steps will be handled in a later iteration.

Output your build result as JSON:
{
    "completed_steps": [
        {
            "step_id": 1,
            "status": "completed|skipped|failed",
            "action_taken": "What was actually done",
            "files_affected": ["list of file paths"],
            "notes": "Any relevant observations"
        }
    ],
    "artifacts_created": [
        {"path": "file/path", "action": "created|modified|deleted"}
    ],
    "issues_encountered": ["List of problems hit during build"],
    "next_steps_suggested": ["Optional suggestions for reviewer"]
}"""


class BuilderNode(Node):
    """
    Executes the implementation plan, generating/modifying code.

    Inputs: Plan from PlannerNode
    Outputs: Build results with artifacts and status
    """

    def __init__(self, llm: LLMClient):
        super().__init__("Builder")
        self.llm = llm

    def prep(self, state: SharedState) -> dict[str, Any]:
        """Prepare build context from current plan."""
        state.status = FlowStatus.BUILDING

        return {
            "plan": state.current_plan,
            "workspace": state.workspace,
            "task_content": state.task_content,
            "iteration": state.current_iteration,
            "existing_artifacts": [a.path for a in state.artifacts],
        }

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute the build plan via LLM."""
        plan = context["plan"]
        prompt = self._build_prompt(context)

        steps = plan.get("steps", [])
        capped = steps[:MAX_STEPS_PER_BUILD]
        logger.info("Executing build for iteration %d", context["iteration"])
        logger.info("Plan has %d steps; executing first %d", len(steps), len(capped))

        try:
            return self.llm.complete_json(prompt, system=BUILDER_SYSTEM)
        except LLMResponseError as e:
            logger.error("Build LLM call failed: %s (raw: %.200s)", e, e.raw)
            raise

    def post(self, state: SharedState, prep_result: dict, exec_result: dict) -> str:
        """Record build results and transition to review."""
        record = state.current_record()
        if record:
            record.build_result = exec_result

        # Track artifacts
        for artifact in exec_result.get("artifacts_created", []):
            state.add_artifact(artifact["path"], artifact["action"])

        # Check for build failures
        issues = exec_result.get("issues_encountered", [])
        match len(issues):
            case 0:
                pass
            case n:
                logger.warning("Build encountered %d issues", n)
                for issue in issues:
                    logger.warning("  - %s", issue)

        state.touch()
        return "review"

    def _build_prompt(self, context: dict[str, Any]) -> str:
        plan = context["plan"]
        all_steps = plan.get("steps", [])
        steps_to_run = all_steps[:MAX_STEPS_PER_BUILD]
        remaining = len(all_steps) - len(steps_to_run)

        parts = [
            "# Implementation Plan to Execute\n",
            f"Summary: {plan.get('summary', 'No summary')}",
            "\n## Steps (execute only these):\n",
        ]

        for step in steps_to_run:
            parts.append(
                f"{step.get('id', '?')}. [{step.get('type', 'task')}] "
                f"{step.get('description', 'No description')}\n"
                f"   Target: {step.get('target', 'N/A')}\n"
                f"   Details: {step.get('details', 'N/A')}\n"
            )

        if remaining > 0:
            parts.append(
                f"\n(There are {remaining} more steps in the full plan; they will be run in a later iteration.)\n"
            )

        if plan.get("dependencies"):
            parts.append(f"\n## Dependencies: {', '.join(plan['dependencies'])}\n")

        if context.get("existing_artifacts"):
            parts.append("\n## Existing Artifacts:\n")
            for path in context["existing_artifacts"]:
                parts.append(f"- {path}\n")

        parts.extend(
            [
                "\n# Context",
                f"- Workspace: {context['workspace']}",
                f"- Iteration: {context['iteration']}",
                "\n\nExecute this plan and report results as JSON.",
            ]
        )

        return "\n".join(parts)

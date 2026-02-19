"""Planner node for rtw architect loop."""

import logging
from typing import Any

from rtw.core import FlowStatus, Node, SharedState
from rtw.llm import LLMClient

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """You are a senior software architect planning implementation tasks.
Your role is to analyze requirements and create detailed, actionable implementation plans.

Output your plan as JSON with this structure:
{
    "summary": "Brief summary of what will be built",
    "steps": [
        {
            "id": 1,
            "description": "What to do",
            "type": "create|modify|delete|research",
            "target": "file path or component name",
            "details": "Specific implementation details"
        }
    ],
    "dependencies": ["External packages or resources needed"],
    "risks": ["Potential issues or blockers"],
    "estimated_complexity": "low|medium|high"
}"""


class PlannerNode(Node):
    """
    Analyzes task requirements and generates an implementation plan.

    Inputs: Task content from .md file, previous iteration feedback
    Outputs: Structured plan with steps, dependencies, risks
    """

    def __init__(self, llm: LLMClient):
        super().__init__("Planner")
        self.llm = llm

    def prep(self, state: SharedState) -> dict[str, Any]:
        """Gather context for planning."""
        state.status = FlowStatus.PLANNING
        state.start_iteration()

        context = {
            "task_content": state.task_content,
            "iteration": state.current_iteration,
            "workspace": state.workspace,
        }

        # Include feedback from previous iteration if available
        if len(state.history) > 1:
            prev_record = state.history[-2]
            if prev_record.review_result:
                context["previous_feedback"] = prev_record.review_result.get("feedback", "")
                context["previous_plan"] = prev_record.plan

        return context

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate implementation plan via LLM."""
        prompt = self._build_prompt(context)

        logger.info(f"Generating plan for iteration {context['iteration']}")
        result = self.llm.complete_json(prompt, system=PLANNER_SYSTEM)

        if "error" in result:
            logger.warning(f"Plan generation had issues: {result.get('error')}")

        return result

    def post(self, state: SharedState, prep_result: dict, exec_result: dict) -> str:
        """Store plan and transition to build phase."""
        state.current_plan = exec_result

        record = state.current_record()
        if record:
            record.plan = exec_result

        state.touch()

        # Check for blocking issues in the plan
        if exec_result.get("error"):
            logger.warning("Plan generation failed, may need retry")

        risks = exec_result.get("risks", [])
        for risk in risks:
            if "block" in risk.lower() or "cannot" in risk.lower():
                logger.warning(f"Potential blocker identified: {risk}")

        return "build"

    def _build_prompt(self, context: dict[str, Any]) -> str:
        parts = [
            "# Task Requirements\n",
            context["task_content"],
            "\n# Context\n",
            f"- Workspace: {context['workspace']}",
            f"- Iteration: {context['iteration']}",
        ]

        if context.get("previous_feedback"):
            parts.extend(
                [
                    "\n# Feedback from Previous Iteration\n",
                    context["previous_feedback"],
                    "\n# Previous Plan (to improve upon)\n",
                    str(context.get("previous_plan", {})),
                ]
            )

        parts.append("\n\nGenerate a detailed implementation plan as JSON.")

        return "\n".join(parts)

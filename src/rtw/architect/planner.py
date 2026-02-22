"""Planner node for rtw architect loop."""

import json
import logging
from typing import Any

from rtw.agent import AgentBackend, AgentError
from rtw.core import FlowStatus, Node, SharedState

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """You are a senior software architect planning implementation tasks.

## Your Role
Analyze requirements and create detailed, actionable implementation plans
that a builder agent can execute autonomously.

## Planning Strategy
1. ANALYZE: Read the task requirements carefully. Identify what already exists vs what needs to be created.
2. PRIORITIZE: Order steps by dependency - foundational work first, then features, then polish.
3. SCOPE: Limit to 3-5 concrete steps per iteration (~5 min of work). Plan remaining work for follow-up iterations.
4. SPECIFY: Include enough detail that the builder doesn't need to make judgment calls.

## Learning from History
If previous iteration feedback or lessons learned are provided, integrate them:
- Don't repeat approaches that failed
- Build on what worked well
- Address specific issues raised by the reviewer

## Output Format
Return ONLY valid JSON (no markdown, no explanation):
{
    "summary": "Brief summary of what will be built this iteration",
    "steps": [
        {
            "id": 1,
            "description": "Clear action to take",
            "type": "create|modify|delete|research",
            "target": "file path or component name",
            "details": "Specific implementation details - be precise"
        }
    ]
}"""


class PlannerNode(Node):
    """Analyzes task requirements and generates an implementation plan.

    Consumes reviewer feedback as opaque text rather than parsing specific keys,
    making the planner resilient to variations in reviewer output structure.
    """

    def __init__(self, agent: AgentBackend):
        super().__init__("Planner")
        self.agent = agent

    def prep(self, state: SharedState) -> dict[str, Any]:
        """Gather context for planning."""
        state.status = FlowStatus.PLANNING
        state.start_iteration()

        context = {
            "task_content": state.task_content,
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
            "iterations_remaining": state.max_iterations - state.current_iteration,
            "workspace": state.workspace,
            "lessons_learned": state.get_lessons_summary(),
            "existing_artifacts": [a.path for a in state.artifacts],
        }

        if len(state.history) > 1:
            prev_record = state.history[-2]
            if prev_record.review_result:
                context["previous_review"] = _format_review_as_text(prev_record.review_result)
                context["previous_plan"] = prev_record.plan

        return context

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate implementation plan via LLM."""
        prompt = self._build_prompt(context)

        logger.info("Generating plan for iteration %d", context["iteration"])
        try:
            return self.agent.complete_json(prompt, system=PLANNER_SYSTEM)
        except AgentError as e:
            logger.error("Plan generation failed: %s", e)
            raise

    def post(self, state: SharedState, prep_result: dict, exec_result: dict) -> str:
        """Store plan and transition to execution phase."""
        state.current_plan = exec_result

        record = state.current_record()
        if record:
            record.plan = state.current_plan

        state.touch()
        return "execute"

    def _build_prompt(self, context: dict[str, Any]) -> str:
        iterations_remaining = context["iterations_remaining"]
        budget_note = (
            f"You have {iterations_remaining} iterations remaining. "
            if iterations_remaining <= 3
            else ""
        )
        if iterations_remaining == 1:
            budget_note = "WARNING: This is your LAST iteration. Prioritize completing the most critical remaining work. "

        parts = [
            "# Task Requirements\n",
            context["task_content"],
            "\n# Context\n",
            f"- Workspace: {context['workspace']}",
            f"- Iteration: {context['iteration']} of {context['max_iterations']}",
            f"- {budget_note}Plan accordingly." if budget_note else "",
        ]

        if context.get("existing_artifacts"):
            parts.append("\n# Files Already Created/Modified")
            for path in context["existing_artifacts"]:
                parts.append(f"- {path}")

        if context.get("lessons_learned"):
            parts.append(f"\n{context['lessons_learned']}")

        if context.get("previous_review"):
            parts.append("\n# Reviewer Feedback from Previous Iteration\n")
            parts.append(context["previous_review"])

        if context.get("previous_plan"):
            parts.append("\n# Previous Plan (to improve upon)\n")
            parts.append(str(context["previous_plan"]))

        parts.append("\n\nGenerate a detailed implementation plan as JSON.")

        return "\n".join(parts)


def _format_review_as_text(review: dict) -> str:
    """Render a review result as readable text for the planner LLM.

    Uses the assessment field when present; falls back to formatted JSON
    for resilience against unexpected LLM output structures.
    """
    assessment = review.get("assessment")
    if assessment:
        score = review.get("score", "N/A")
        verdict = review.get("verdict", "N/A")
        return f"Verdict: {verdict} | Score: {score}/100\n\n{assessment}"

    # Fallback: dump whatever structure we received as formatted JSON.
    # The planner LLM can interpret JSON text perfectly well.
    return json.dumps(review, indent=2)

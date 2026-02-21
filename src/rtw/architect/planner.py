"""Planner node for rtw architect loop."""

import logging
from typing import Any

from rtw.agent import AgentBackend, AgentError
from rtw.core import FlowStatus, Node, SharedState

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """You are a senior software architect planning implementation tasks.

## Your Role
Analyze requirements and create detailed, actionable implementation plans that a builder agent can execute autonomously.

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
    "rationale": "Why these steps were chosen and in this order",
    "steps": [
        {
            "id": 1,
            "description": "Clear action to take",
            "type": "create|modify|delete|research",
            "target": "file path or component name",
            "details": "Specific implementation details - be precise",
            "acceptance": "How to verify this step succeeded"
        }
    ],
    "dependencies": ["External packages or resources needed"],
    "risks": ["Potential issues or blockers"],
    "estimated_complexity": "low|medium|high"
}

## Example
For a task "Add user authentication to Flask app":
{
    "summary": "Set up authentication foundation with User model and login endpoint",
    "rationale": "Must establish User model before building auth flows; login is the core feature",
    "steps": [
        {
            "id": 1,
            "description": "Create User model with password hashing",
            "type": "create",
            "target": "app/models/user.py",
            "details": "SQLAlchemy model with id, email, password_hash fields. Use werkzeug.security for hashing.",
            "acceptance": "File exists, imports successfully, model has required fields"
        },
        {
            "id": 2,
            "description": "Add login endpoint",
            "type": "create",
            "target": "app/routes/auth.py",
            "details": "POST /login accepting email/password, returning JWT token on success",
            "acceptance": "Endpoint responds to POST, validates credentials, returns token"
        }
    ],
    "dependencies": ["flask-sqlalchemy", "pyjwt", "werkzeug"],
    "risks": ["Database migrations may be needed"],
    "estimated_complexity": "medium"
}"""


class PlannerNode(Node):
    """
    Analyzes task requirements and generates an implementation plan.

    Inputs: Task content from .md file, previous iteration feedback
    Outputs: Structured plan with steps, dependencies, risks
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

        logger.info("Generating plan for iteration %d", context["iteration"])
        try:
            return self.agent.complete_json(prompt, system=PLANNER_SYSTEM)
        except AgentError as e:
            logger.error("Plan generation failed: %s", e)
            raise

    def post(self, state: SharedState, prep_result: dict, exec_result: dict) -> str:
        """Store plan and transition to build phase."""
        state.current_plan = exec_result

        record = state.current_record()
        if record:
            record.plan = state.current_plan

        state.touch()

        risks = exec_result.get("risks", [])
        for risk in risks:
            match risk.lower():
                case r if "block" in r or "cannot" in r:
                    logger.warning("Potential blocker identified: %s", risk)

        return "build"

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

        # Include existing artifacts so planner knows what's already done
        if context.get("existing_artifacts"):
            parts.append("\n# Files Already Created/Modified")
            for path in context["existing_artifacts"]:
                parts.append(f"- {path}")

        # Include cumulative lessons learned
        if context.get("lessons_learned"):
            parts.append(f"\n{context['lessons_learned']}")

        if context.get("previous_feedback"):
            feedback = context["previous_feedback"]
            parts.append("\n# Feedback from Previous Iteration\n")

            # Handle structured feedback format
            if isinstance(feedback, dict):
                if feedback.get("what_worked"):
                    parts.append("## What Worked (continue doing these):")
                    for item in feedback["what_worked"]:
                        parts.append(f"- {item}")

                if feedback.get("what_failed"):
                    parts.append("\n## What Failed (avoid these approaches):")
                    for item in feedback["what_failed"]:
                        parts.append(f"- {item}")

                if feedback.get("specific_fixes"):
                    parts.append("\n## Specific Fixes Needed (address these):")
                    for item in feedback["specific_fixes"]:
                        parts.append(f"- {item}")

                if feedback.get("priority_order"):
                    parts.append("\n## Priority Order:")
                    for i, item in enumerate(feedback["priority_order"], 1):
                        parts.append(f"{i}. {item}")
            else:
                # Fallback for string feedback
                parts.append(str(feedback))

            parts.extend(
                [
                    "\n# Previous Plan (to improve upon)\n",
                    str(context.get("previous_plan", {})),
                ]
            )

        parts.append("\n\nGenerate a detailed implementation plan as JSON.")

        return "\n".join(parts)

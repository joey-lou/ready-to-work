"""Reviewer node for rtw architect loop."""

import logging
from typing import Any

from rtw.core import FlowStatus, Node, SharedState
from rtw.llm import LLMClient, LLMResponseError

logger = logging.getLogger(__name__)

REVIEWER_SYSTEM = """You are a senior code reviewer and QA engineer.
Evaluate the build results against the original requirements.

Return the review as JSON in your response. Do not write the review to a file.

Output your review as JSON:
{
    "verdict": "approve|iterate|blocked",
    "score": 0-100,
    "summary": "Brief assessment of the work",
    "strengths": ["What was done well"],
    "issues": [
        {
            "severity": "critical|major|minor",
            "description": "What's wrong",
            "suggestion": "How to fix it"
        }
    ],
    "feedback": "Detailed feedback for the next iteration if needed",
    "blocking_reason": "If verdict is 'blocked', explain why human intervention is needed"
}

Verdicts:
- "approve": Work meets requirements, ready to complete
- "iterate": Work needs improvement, provide feedback for next iteration
- "blocked": Cannot proceed without human intervention (missing info, ambiguous requirements, external dependency)"""


class ReviewerNode(Node):
    """
    Reviews build results against requirements and decides next action.

    Inputs: Build results, original task, plan
    Outputs: Review verdict (approve/iterate/blocked) with feedback
    """

    def __init__(self, llm: LLMClient):
        super().__init__("Reviewer")
        self.llm = llm

    def prep(self, state: SharedState) -> dict[str, Any]:
        """Gather all context for review."""
        state.status = FlowStatus.REVIEWING

        record = state.current_record()

        return {
            "task_content": state.task_content,
            "plan": record.plan if record else None,
            "build_result": record.build_result if record else None,
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
            "artifacts": [{"path": a.path, "action": a.action} for a in state.artifacts],
            "history_length": len(state.history),
        }

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        """Evaluate build results via LLM."""
        prompt = self._build_prompt(context)

        logger.info("Reviewing iteration %d", context["iteration"])
        try:
            return self.llm.complete_json(prompt, system=REVIEWER_SYSTEM)
        except LLMResponseError as e:
            logger.error("Review LLM call failed: %s (raw: %.200s)", e, e.raw)
            raise

    def post(self, state: SharedState, prep_result: dict, exec_result: dict) -> str | None:
        """Process review verdict and route accordingly."""
        record = state.current_record()
        if record:
            record.review_result = exec_result

        verdict = exec_result.get("verdict", "iterate")
        score = exec_result.get("score", 0)

        logger.info("Review verdict: %s (score: %s)", verdict, score)

        match verdict:
            case "approve":
                state.status = FlowStatus.COMPLETED
                state.final_summary = exec_result.get("summary", "Task completed successfully")
                logger.info("Task approved - flow complete")
                return None
            case "blocked":
                state.status = FlowStatus.BLOCKED
                state.blocking_reason = exec_result.get("blocking_reason", "Unknown blocking issue")
                logger.warning("Task blocked: %s", state.blocking_reason)
                return None
            case _:  # iterate
                feedback = exec_result.get("feedback", "")
                logger.info("Iteration needed. Feedback: %.100s", feedback)
                state.touch()
                return "plan"

    def _build_prompt(self, context: dict[str, Any]) -> str:
        parts = [
            "# Original Requirements\n",
            context["task_content"],
            "\n# Implementation Plan\n",
            str(context.get("plan", {})),
            "\n# Build Results\n",
            str(context.get("build_result", {})),
            "\n# Artifacts Created\n",
        ]

        for artifact in context.get("artifacts", []):
            parts.append(f"- {artifact['action']}: {artifact['path']}\n")

        parts.extend(
            [
                "\n# Iteration Info",
                f"- Current iteration: {context['iteration']} of {context['max_iterations']}",
                f"- Total history entries: {context['history_length']}",
                "\n\nReview this work and provide your verdict as JSON.",
            ]
        )

        return "\n".join(parts)

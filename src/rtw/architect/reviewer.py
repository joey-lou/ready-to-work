"""Reviewer node for rtw architect loop."""

import logging
from pathlib import Path
from typing import Any

from rtw.agent import AgentBackend, AgentError
from rtw.core import FlowStatus, Node, SharedState

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_FOR_REVIEW = 10000  # chars
MAX_TOTAL_FILE_CONTENT = 50000  # chars total across all files

REVIEWER_SYSTEM = """You are a senior code reviewer and QA engineer.

## Your Role
Evaluate build results against original requirements. Your review guides the next iteration.

## Review Strategy
1. COMPARE: Check each requirement against what was built
2. VERIFY: Look at actual file contents to confirm implementation quality
3. ASSESS: Identify what works, what's missing, what needs fixing
4. GUIDE: Provide actionable feedback that helps the next iteration succeed

## Verdict Guidelines
- "approve": All core requirements met, code is functional and reasonably clean
- "iterate": Progress was made but more work needed. Be specific about what's missing.
- "blocked": Cannot proceed without human intervention (missing credentials, unclear requirements, external dependency unavailable)

## Budget Awareness
Consider iterations remaining when reviewing:
- Many iterations left: Be thorough, flag all issues
- Few iterations left: Focus on critical issues only, defer nice-to-haves
- Last iteration: Only block for truly critical problems

## Output Format
Return ONLY valid JSON (no markdown, no explanation):
{
    "verdict": "approve|iterate|blocked",
    "score": 0-100,
    "summary": "Brief assessment of the work",
    "requirements_status": [
        {"requirement": "description", "status": "met|partial|missing", "notes": "details"}
    ],
    "strengths": ["What was done well - be specific"],
    "issues": [
        {
            "severity": "critical|major|minor",
            "description": "What's wrong",
            "suggestion": "How to fix it",
            "blocks_approval": true|false
        }
    ],
    "feedback": {
        "what_worked": ["Approaches that succeeded - keep doing these"],
        "what_failed": ["Approaches that didn't work - avoid these"],
        "specific_fixes": ["Exact changes needed for next iteration"],
        "priority_order": ["Most important fix first, then second, etc."]
    },
    "lessons_learned": ["Key insights to remember for future iterations"],
    "blocking_reason": "If verdict is 'blocked', explain why human intervention is needed"
}"""


class ReviewerNode(Node):
    """
    Reviews build results against requirements and decides next action.

    Inputs: Build results, original task, plan
    Outputs: Review verdict (approve/iterate/blocked) with feedback
    """

    def __init__(self, agent: AgentBackend):
        super().__init__("Reviewer")
        self.agent = agent

    def prep(self, state: SharedState) -> dict[str, Any]:
        """Gather all context for review."""
        state.status = FlowStatus.REVIEWING

        record = state.current_record()

        # Read actual file contents for artifacts (within size limits)
        artifact_contents = self._read_artifact_contents(state.workspace, state.artifacts)

        return {
            "task_content": state.task_content,
            "plan": record.plan if record else None,
            "build_result": record.build_result if record else None,
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
            "iterations_remaining": state.max_iterations - state.current_iteration,
            "artifacts": [{"path": a.path, "action": a.action} for a in state.artifacts],
            "artifact_contents": artifact_contents,
            "history_length": len(state.history),
            "lessons_learned": state.get_lessons_summary(),
        }

    def _read_artifact_contents(self, workspace: str, artifacts: list) -> dict[str, str]:
        """Read contents of artifact files for review (within size limits)."""
        contents: dict[str, str] = {}
        total_size = 0

        for artifact in artifacts:
            if artifact.action == "deleted":
                continue

            file_path = Path(workspace) / artifact.path
            if not file_path.exists():
                contents[artifact.path] = "(file not found)"
                continue

            if not file_path.is_file():
                continue

            try:
                file_size = file_path.stat().st_size
                if file_size > MAX_FILE_SIZE_FOR_REVIEW:
                    contents[artifact.path] = f"(file too large: {file_size} bytes)"
                    continue

                if total_size + file_size > MAX_TOTAL_FILE_CONTENT:
                    contents[artifact.path] = "(skipped: total content limit reached)"
                    continue

                content = file_path.read_text(errors="replace")
                contents[artifact.path] = content
                total_size += len(content)

            except OSError as e:
                contents[artifact.path] = f"(error reading: {e})"

        return contents

    def exec(self, context: dict[str, Any]) -> dict[str, Any]:
        """Evaluate build results via LLM."""
        prompt = self._build_prompt(context)

        logger.info("Reviewing iteration %d", context["iteration"])
        try:
            return self.agent.complete_json(prompt, system=REVIEWER_SYSTEM)
        except AgentError as e:
            logger.error("Review failed: %s", e)
            raise

    def post(self, state: SharedState, prep_result: dict, exec_result: dict) -> str | None:
        """Process review verdict and route accordingly."""
        record = state.current_record()
        if record:
            record.review_result = exec_result

        verdict = exec_result.get("verdict", "iterate")
        score = exec_result.get("score", 0)

        logger.info("Review verdict: %s (score: %s)", verdict, score)

        # Capture lessons learned from reviewer
        for lesson in exec_result.get("lessons_learned", []):
            state.add_lesson("insight", lesson)

        # Capture strengths as successes
        for strength in exec_result.get("strengths", []):
            state.add_lesson("success", strength)

        # Capture critical issues as failures
        for issue in exec_result.get("issues", []):
            if issue.get("severity") == "critical":
                state.add_lesson("failure", issue.get("description", "Unknown issue"))

        match verdict:
            case "approve":
                state.status = FlowStatus.COMPLETED
                state.final_summary = exec_result.get("summary", "Task completed successfully")
                logger.info("Task approved - flow complete")
                return None
            case "blocked":
                state.status = FlowStatus.BLOCKED
                state.blocking_reason = exec_result.get("blocking_reason", "Unknown blocking issue")
                state.add_lesson("blocker_resolved", f"Blocked: {state.blocking_reason}")
                logger.warning("Task blocked: %s", state.blocking_reason)
                return None
            case _:  # iterate
                feedback = exec_result.get("feedback", {})
                if isinstance(feedback, dict):
                    summary = "; ".join(feedback.get("specific_fixes", [])[:2])
                else:
                    summary = str(feedback)[:100]
                logger.info("Iteration needed. Feedback: %s", summary)
                state.touch()
                return "plan"

    def _build_prompt(self, context: dict[str, Any]) -> str:
        iterations_remaining = context.get("iterations_remaining", 10)
        budget_guidance = ""
        if iterations_remaining <= 2:
            budget_guidance = (
                "LOW BUDGET: Focus only on critical issues. Minor improvements can be deferred."
            )
        elif iterations_remaining == 1:
            budget_guidance = "LAST ITERATION: Only block for truly critical problems. Approve if core functionality works."

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
            parts.append(f"- {artifact['action']}: {artifact['path']}")

        # Include actual file contents for informed review
        artifact_contents = context.get("artifact_contents", {})
        if artifact_contents:
            parts.append("\n# File Contents (for verification)\n")
            for path, content in artifact_contents.items():
                if content.startswith("("):  # Error or skip message
                    parts.append(f"## {path}\n{content}\n")
                else:
                    parts.append(f"## {path}\n```\n{content}\n```\n")

        # Include cumulative lessons
        if context.get("lessons_learned"):
            parts.append(f"\n{context['lessons_learned']}")

        parts.extend(
            [
                "\n# Iteration Info",
                f"- Current iteration: {context['iteration']} of {context['max_iterations']}",
                f"- Iterations remaining: {iterations_remaining}",
                f"- {budget_guidance}" if budget_guidance else "",
                f"- Total history entries: {context['history_length']}",
                "\n\nReview this work and provide your verdict as JSON.",
            ]
        )

        return "\n".join(parts)

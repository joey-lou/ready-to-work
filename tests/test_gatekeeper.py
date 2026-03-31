"""Gatekeeper: stage-specific validation and planner completion edge cases."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from rtw.agent import AgentResult
from rtw.core.gatekeeper import (
    ValidationIssue,
    retry_with_corrections,
    validate_planner_output,
    validate_reviewer_output,
)


def _write_minimal_plan(run_dir: Path) -> None:
    (run_dir / "PLAN.md").write_text(
        "# P\n\n## Steps\n1. a\n\n## Lessons\n\n",
        encoding="utf-8",
    )


def test_planner_validates_not_started_plan_status():
    """plan_status NOT_STARTED is accepted (enum-aligned)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _write_minimal_plan(d)
        (d / "SUBTASK.md").write_text("# S\n\n## Acceptance criteria\n- [ ] x\n", encoding="utf-8")
        (d / "state.json").write_text(json.dumps({"plan_status": "NOT_STARTED"}), encoding="utf-8")
        r = validate_planner_output(d)
        assert r.passed


def test_planner_skips_subtask_when_completed():
    """When plan_status is COMPLETED, SUBTASK.md need not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _write_minimal_plan(d)
        (d / "state.json").write_text(json.dumps({"plan_status": "COMPLETED"}), encoding="utf-8")
        r = validate_planner_output(d)
        assert r.passed


def test_reviewer_requires_exact_review_heading():
    """'## Review section' does not satisfy reviewer gate."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "SUBTASK.md").write_text(
            "# S\n\n## Acceptance criteria\n- [x] a\n\n## Review section\nx\n",
            encoding="utf-8",
        )
        (d / "state.json").write_text(json.dumps({"subtask_status": "PASSED"}), encoding="utf-8")
        r = validate_reviewer_output(d)
        assert not r.passed


def test_reviewer_rejects_prompt_context_after_review_section():
    """SUBTASK.md must not echo # TASK.md / # PLAN.md etc. after ## Review."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "SUBTASK.md").write_text(
            "# S\n\n## Acceptance criteria\n- [x] a\n\n## Review\nok\n\n# TASK.md\nstuff\n",
            encoding="utf-8",
        )
        (d / "state.json").write_text(json.dumps({"subtask_status": "PASSED"}), encoding="utf-8")
        r = validate_reviewer_output(d)
        assert not r.passed
        assert any("prompt context" in i.message for i in r.issues)


def test_retry_uses_validate_callable():
    """Reviewer retry re-validates with validate_reviewer_output, not planner rules."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "SUBTASK.md").write_text(
            "# S\n\n## Acceptance criteria\n- [x] a\n\n## Review\nok\n",
            encoding="utf-8",
        )
        (d / "state.json").write_text(json.dumps({"subtask_status": "PASSED"}), encoding="utf-8")
        agent = MagicMock()
        agent.execute.return_value = AgentResult(success=True, output="ok")
        assert validate_planner_output(d).passed is False
        assert validate_reviewer_output(d).passed is True
        ok = retry_with_corrections(
            agent,
            Path(tmp),
            d,
            [ValidationIssue("error", "SUBTASK.md", "fix")],
            max_retries=1,
            validate=validate_reviewer_output,
        )
        assert ok is True


def test_planner_warns_after_repeated_identical_lessons():
    """Third consecutive planner pass with the same ## Lessons body yields a warning."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        plan_body = "# P\n\n## Steps\n1. a\n\n## Lessons\n- same lesson\n\n"
        (d / "PLAN.md").write_text(plan_body, encoding="utf-8")
        (d / "SUBTASK.md").write_text("# S\n\n## Acceptance criteria\n- [ ] x\n", encoding="utf-8")
        (d / "state.json").write_text(json.dumps({"plan_status": "IN_PROGRESS"}), encoding="utf-8")

        r1 = validate_planner_output(d)
        assert r1.passed
        assert not any("Lessons unchanged" in i.message for i in r1.issues)

        r2 = validate_planner_output(d)
        assert r2.passed
        assert not any("Lessons unchanged" in i.message for i in r2.issues)

        r3 = validate_planner_output(d)
        assert r3.passed
        assert any("Lessons unchanged" in i.message for i in r3.issues)

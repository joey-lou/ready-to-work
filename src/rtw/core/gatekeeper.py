"""Gatekeeper: deterministic validation and retry for agent outputs."""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rtw.agent import AgentBackend
from rtw.core.state import PlanStatus

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 2

_PLANNER_SKELETON = """PLAN.md format:
## Steps
1. **Step name** — description  ✓
2. **Step name** — description

## Lessons
- (optional) insight from past review cycles

SUBTASK.md format:
# Subtask: <step name>
<instructions for the executor>

## Acceptance criteria
- [ ] objectively checkable criterion (command + expected outcome, or exact symbols/values)
- [ ] another criterion
"""

_REVIEWER_SKELETON = """SUBTASK.md post-review format:
## Acceptance criteria
- [x] criterion met
- [ ] criterion failed — one-line reason

## Review
Brief findings.

(No TASK.md / PLAN.md / prompt dumps after ## Review.)
"""


@dataclass
class ValidationIssue:
    """Single validation problem found in agent output."""

    level: str  # "error" or "warning"
    document: str  # Document name (PLAN.md, SUBTASK.md, state.json)
    message: str


@dataclass
class GateResult:
    """Result of gatekeeper validation."""

    passed: bool
    issues: list[ValidationIssue]
    repairs_made: list[str]


def _plan_status_valid_values() -> list[str]:
    return [e.value for e in PlanStatus]


def _read_json_field(path: Path, field: str) -> str | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        v = data.get(field)
        return str(v) if v is not None else None
    except (json.JSONDecodeError, OSError):
        return None


def validate_planner_output(run_dir: Path) -> GateResult:
    """Validate Planner outputs: PLAN.md, SUBTASK.md (unless completed), state.json."""
    issues: list[ValidationIssue] = []
    repairs: list[str] = []

    plan_path = run_dir / "PLAN.md"
    subtask_path = run_dir / "SUBTASK.md"
    state_path = run_dir / "state.json"

    plan_status = _read_json_field(state_path, "plan_status")
    skip_subtask = plan_status == PlanStatus.COMPLETED.value

    issues.extend(_validate_plan_document(plan_path))
    if not skip_subtask:
        issues.extend(_validate_subtask_document(subtask_path))
    issues.extend(_validate_state_json(state_path, "plan_status", _plan_status_valid_values()))

    errors = [iss for iss in issues if iss.level == "error"]
    return GateResult(passed=len(errors) == 0, issues=issues, repairs_made=repairs)


def _validate_plan_document(plan_path: Path) -> list[ValidationIssue]:
    """Validate PLAN.md structure."""
    issues = []
    if not plan_path.exists() or plan_path.stat().st_size == 0:
        issues.append(
            ValidationIssue(level="error", document="PLAN.md", message="File is missing or empty")
        )
        return issues

    plan_text = plan_path.read_text()
    if not re.search(r"^##\s+Steps", plan_text, re.MULTILINE):
        issues.append(
            ValidationIssue(level="error", document="PLAN.md", message="Missing '## Steps' section")
        )
    if not re.search(r"^\d+\.\s+", plan_text, re.MULTILINE):
        issues.append(
            ValidationIssue(
                level="error",
                document="PLAN.md",
                message="'## Steps' section has no numbered items",
            )
        )
    if not re.search(r"^##\s+Lessons", plan_text, re.MULTILINE):
        issues.append(
            ValidationIssue(
                level="error", document="PLAN.md", message="Missing '## Lessons' section"
            )
        )
    return issues


def _validate_subtask_document(subtask_path: Path) -> list[ValidationIssue]:
    """Validate SUBTASK.md structure for planner output."""
    issues = []
    if not subtask_path.exists() or subtask_path.stat().st_size == 0:
        issues.append(
            ValidationIssue(
                level="error", document="SUBTASK.md", message="File is missing or empty"
            )
        )
        return issues

    subtask_text = subtask_path.read_text()
    if not re.search(r"^##\s+Acceptance criteria", subtask_text, re.MULTILINE):
        issues.append(
            ValidationIssue(
                level="error",
                document="SUBTASK.md",
                message="Missing '## Acceptance criteria' section",
            )
        )
    if not re.search(r"^-\s+\[[ x]\]", subtask_text, re.MULTILINE):
        issues.append(
            ValidationIssue(
                level="error",
                document="SUBTASK.md",
                message="'## Acceptance criteria' has no checklist items",
            )
        )
    return issues


def _validate_state_json(
    state_path: Path, status_field: str, valid_values: list[str]
) -> list[ValidationIssue]:
    """Validate state.json structure and status field."""
    issues = []
    if not state_path.exists():
        issues.append(
            ValidationIssue(level="error", document="state.json", message="File is missing")
        )
        return issues

    try:
        data = json.loads(state_path.read_text())
        status_value = data.get(status_field)
        if status_value not in valid_values:
            issues.append(
                ValidationIssue(
                    level="error",
                    document="state.json",
                    message=f"Invalid {status_field}: {status_value}",
                )
            )
    except (json.JSONDecodeError, KeyError) as e:
        issues.append(
            ValidationIssue(level="error", document="state.json", message=f"Invalid JSON: {e}")
        )
    return issues


def validate_reviewer_output(run_dir: Path) -> GateResult:
    """Validate Reviewer outputs: SUBTASK.md (with review), state.json."""
    issues: list[ValidationIssue] = []
    repairs: list[str] = []

    subtask_path = run_dir / "SUBTASK.md"
    state_path = run_dir / "state.json"

    issues.extend(_validate_subtask_review(subtask_path))
    issues.extend(
        _validate_state_json(state_path, "subtask_status", ["REVISE", "PASSED", "BLOCKED"])
    )

    errors = [iss for iss in issues if iss.level == "error"]
    return GateResult(passed=len(errors) == 0, issues=issues, repairs_made=repairs)


def _validate_subtask_review(subtask_path: Path) -> list[ValidationIssue]:
    """Validate SUBTASK.md has review section and marked criteria."""
    issues = []
    if not subtask_path.exists() or subtask_path.stat().st_size == 0:
        issues.append(
            ValidationIssue(
                level="error", document="SUBTASK.md", message="File is missing or empty"
            )
        )
        return issues

    subtask_text = subtask_path.read_text()
    if not re.search(r"^##\s+Acceptance criteria", subtask_text, re.MULTILINE):
        issues.append(
            ValidationIssue(
                level="error",
                document="SUBTASK.md",
                message="Missing '## Acceptance criteria' section",
            )
        )
    if not re.search(r"(?m)^##\s+Review\s*$", subtask_text):
        issues.append(
            ValidationIssue(
                level="error",
                document="SUBTASK.md",
                message="Missing exact heading '## Review' (own line; not e.g. '## Review section')",
            )
        )

    criteria_section_match = re.search(
        r"^##\s+Acceptance criteria\s*\n(.*?)(?=^##|\Z)",
        subtask_text,
        re.MULTILINE | re.DOTALL,
    )
    if criteria_section_match:
        criteria_text = criteria_section_match.group(1)
        if not re.search(r"^-\s+\[x\]", criteria_text, re.MULTILINE):
            issues.append(
                ValidationIssue(
                    level="warning",
                    document="SUBTASK.md",
                    message="No criteria marked with [x] (all incomplete?)",
                )
            )

    review_match = re.search(r"(?m)^##\s+Review\s*$", subtask_text)
    if review_match:
        tail = subtask_text[review_match.end() :]
        if re.search(
            r"(?m)^#\s+(TASK\.md|PLAN\.md|SUBTASK\.md|Changed files|File contents)\b",
            tail,
        ):
            issues.append(
                ValidationIssue(
                    level="error",
                    document="SUBTASK.md",
                    message="Content after '## Review' must not echo prompt context "
                    "(e.g. # TASK.md, # PLAN.md, changed-file or file-contents blocks)",
                )
            )

    return issues


def retry_with_corrections(
    agent: AgentBackend,
    workspace: Path,
    run_dir: Path,
    issues: list[ValidationIssue],
    max_retries: int = MAX_RETRY_ATTEMPTS,
    validate: Callable[[Path], GateResult] | None = None,
) -> bool:
    """Retry agent with correction prompt. Returns True if validation passes after retry."""
    validate_fn = validate or validate_planner_output
    skeleton = _REVIEWER_SKELETON if validate_fn is validate_reviewer_output else _PLANNER_SKELETON
    for attempt in range(1, max_retries + 1):
        error_issues = [iss for iss in issues if iss.level == "error"]
        if not error_issues:
            return True

        correction_prompt = _build_correction_prompt(error_issues, skeleton=skeleton)
        logger.warning("Validation failed (attempt %d/%d). Retrying...", attempt, max_retries)

        try:
            result = agent.execute(workspace, correction_prompt, run_dir=run_dir)
            if not result.success:
                logger.error("Retry attempt %d failed: %s", attempt, result.error)
                return False
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Retry attempt %d raised exception: %s", attempt, e)
            return False

        gate_result = validate_fn(run_dir)
        if gate_result.passed:
            logger.info("Validation passed after retry attempt %d", attempt)
            return True

        issues = gate_result.issues

    logger.error("Validation still failing after %d retries. Proceeding anyway.", max_retries)
    return False


def _build_correction_prompt(issues: list[ValidationIssue], skeleton: str) -> str:
    """Build a correction prompt listing issues and the expected schema skeleton."""
    lines = ["The following issues were found in your output. Fix them.\n"]
    for issue in issues:
        lines.append(f"- {issue.document}: {issue.message}")
    lines.append(
        "\nUse this format skeleton as the target structure (copy/paste and fill in):\n\n"
        f"{skeleton}\n"
    )
    return "\n".join(lines)

#!/usr/bin/env python3
"""CLI entry point for ready-to-work (rtw) architect loop."""

import argparse
import logging
import os
import sys
from pathlib import Path

from rtw import __version__
from rtw.architect import BuilderNode, PlannerNode, ReviewerNode
from rtw.core import Flow, FlowStatus, SharedState
from rtw.llm import KNOWN_MODELS, CursorAgentClient, StubLLMClient
from rtw.storage import StateStorage


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


_MOCK_RESPONSES = {
    "architect": '{"summary": "Mock plan", "steps": [{"id": 1, "description": "Test step", "type": "create", "target": "test.py", "details": "Create test file"}], "dependencies": [], "risks": [], "estimated_complexity": "low"}',
    "developer": '{"completed_steps": [{"step_id": 1, "status": "completed", "action_taken": "Created test file", "files_affected": ["test.py"], "notes": "Done"}], "artifacts_created": [{"path": "test.py", "action": "created"}], "issues_encountered": [], "next_steps_suggested": []}',
    "reviewer": '{"verdict": "approve", "score": 95, "summary": "Task completed successfully", "strengths": ["Clean implementation"], "issues": [], "feedback": "", "blocking_reason": null}',
}


def _make_llm_client(
    mock: bool, model: str | None, workspace: Path
) -> "CursorAgentClient | StubLLMClient":
    """Construct the appropriate LLM client based on flags."""
    if mock:
        logging.getLogger("rtw").info("Using stub LLM client for --mock mode")
        return StubLLMClient(responses=_MOCK_RESPONSES)
    return CursorAgentClient(workspace, model=model) if model else CursorAgentClient(workspace)


def _report_final_status(logger: logging.Logger, final_state: SharedState) -> int:
    """Log final state summary and return appropriate exit code."""
    logger.info("=" * 50)
    logger.info("Flow completed")
    logger.info("=" * 50)
    logger.info("Final status: %s", final_state.status.value)
    logger.info("Iterations: %d", final_state.current_iteration)
    logger.info("Artifacts: %d", len(final_state.artifacts))

    match final_state.status:
        case FlowStatus.COMPLETED:
            logger.info("Summary: %s", final_state.final_summary)
            return 0
        case FlowStatus.BLOCKED:
            logger.warning("Blocked: %s", final_state.blocking_reason)
            return 2
        case _:
            logger.warning("Ended with status: %s", final_state.status.value)
            return 1


def create_architect_flow(llm_client, on_state_change=None) -> Flow:
    """Wire up the Plan -> Build -> Review loop."""
    planner = PlannerNode(llm_client)
    builder = BuilderNode(llm_client)
    reviewer = ReviewerNode(llm_client)

    planner.on("build") >> builder
    builder.on("review") >> reviewer
    reviewer.on("plan") >> planner

    return Flow(start=planner, name="architect", on_state_change=on_state_change)


def run_task(
    task_file: Path,
    workspace: Path,
    max_iterations: int,
    mock: bool = False,
    model: str | None = None,
) -> int:
    """Execute the architect loop on a task file."""
    logger = logging.getLogger("rtw")

    if not task_file.exists():
        logger.error("Task file not found: %s", task_file)
        return 1

    task_content = task_file.read_text()
    logger.info("Loaded task from: %s", task_file)
    logger.info("Task length: %d chars", len(task_content))

    storage = StateStorage(workspace)
    logger.info("Run ID: %s", storage.run_id)
    logger.info("State stored in: %s", storage.base_dir)

    state = SharedState(
        task_file=str(task_file),
        task_content=task_content,
        workspace=str(workspace),
        max_iterations=max_iterations,
    )

    llm_client = _make_llm_client(mock, model, workspace)
    flow = create_architect_flow(llm_client, on_state_change=storage.save)

    logger.info("=" * 50)
    logger.info("Starting architect loop")
    logger.info("=" * 50)

    try:
        final_state = flow.run(state)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        storage.save(state)
        return 130
    except Exception as e:
        logger.error("Flow failed: %s", e)
        storage.save(state)
        return 1

    return _report_final_status(logger, final_state)


def resume_run(
    workspace: Path,
    run_id: str | None = None,
    mock: bool = False,
    model: str | None = None,
) -> int:
    """Resume a previous run from persisted state and continue the architect loop."""
    logger = logging.getLogger("rtw")

    if run_id:
        storage = StateStorage(workspace, run_id)
    else:
        storage = StateStorage.get_latest_run(workspace)
        if not storage:
            logger.error(
                "No previous runs found in %s. If the run is in another project, use: rtw resume -w /path/to/that/project",
                workspace,
            )
            return 1

    state = storage.load()
    if not state:
        logger.error(
            "Could not load state from run %s (missing or invalid state file). "
            "Check that -w points to the project that contains this run (e.g. rtw resume -w /path/to/rts --run-id %s).",
            storage.run_id,
            storage.run_id,
        )
        return 1

    logger.info("Resuming run: %s", storage.run_id)
    logger.info("Previous status: %s, Iteration: %d", state.status.value, state.current_iteration)

    # Reset so the loop continues; planner will set PLANNING and start next iteration
    state.status = FlowStatus.PENDING

    llm_client = _make_llm_client(mock, model, Path(state.workspace))
    flow = create_architect_flow(llm_client, on_state_change=storage.save)

    logger.info("=" * 50)
    logger.info("Continuing architect loop")
    logger.info("=" * 50)

    try:
        final_state = flow.run(state)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        storage.save(state)
        return 130
    except Exception as e:
        logger.error("Flow failed: %s", e)
        storage.save(state)
        return 1

    return _report_final_status(logger, final_state)


def list_runs(workspace: Path) -> int:
    """List all runs in a workspace."""
    runs = StateStorage.list_runs(workspace)

    if not runs:
        print("No runs found")
        return 0

    print(f"Found {len(runs)} runs:\n")
    for run_id in runs:
        storage = StateStorage(workspace, run_id)
        state = storage.load()
        if state:
            print(f"  {run_id}")
            print(f"    Status: {state.status.value}")
            print(f"    Iterations: {state.current_iteration}")
            print(f"    Task: {Path(state.task_file).name}")
            print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="rtw (ready-to-work) - Architect loop for AI-driven development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  rtw -V                           # Show version
  rtw run task.md                  # Run architect loop on task.md
  rtw run task.md --max-iter 5     # Limit to 5 iterations
  rtw run task.md --mock           # Run with mock LLM (no Cursor agent)
  rtw list                         # List previous runs
  rtw resume                       # Resume latest run (in current dir)
  rtw resume --mock                # Resume latest run with mock LLM
  rtw resume -w /path/to/project   # Resume run in another project
  rtw resume --run-id 20240101_120000  # Resume specific run
        """,
    )

    parser.add_argument("-V", "--version", action="version", version=f"rtw {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "-w",
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace directory (default: current dir)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run architect loop on a task file")
    run_parser.add_argument("task_file", type=Path, help="Path to task.md file")
    run_parser.add_argument("--max-iter", type=int, default=10, help="Max iterations (default: 10)")
    run_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Cursor agent model (e.g. sonnet-4.6). Overrides RTW_MODEL env.",
    )
    run_parser.add_argument("--mock", action="store_true", help="Use mock LLM client (for testing)")

    subparsers.add_parser("list", help="List previous runs")

    resume_parser = subparsers.add_parser("resume", help="Resume a previous run")
    resume_parser.add_argument("--run-id", type=str, help="Specific run ID to resume")
    resume_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Cursor agent model. Overrides RTW_MODEL env.",
    )
    resume_parser.add_argument(
        "--mock", action="store_true", help="Use mock LLM client (for testing)"
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    model_arg = getattr(args, "model", None)
    mock_arg = getattr(args, "mock", False)
    resolved_model = model_arg or os.environ.get("RTW_MODEL")
    if resolved_model and not mock_arg:
        skip_validation = os.environ.get("RTW_SKIP_MODEL_VALIDATION", "").strip() not in ("", "0")
        if not skip_validation and resolved_model not in KNOWN_MODELS:
            print(
                f"Error: unknown model {resolved_model!r}.\n"
                f"Available models: {', '.join(sorted(KNOWN_MODELS))}\n"
                "Set RTW_SKIP_MODEL_VALIDATION=1 to bypass if this list is stale.",
                file=sys.stderr,
            )
            sys.exit(1)
        if resolved_model == "auto":
            logging.getLogger("rtw").warning(
                "Model 'auto' may return empty JSON responses; consider using 'sonnet-4.6' for reliability."
            )

    match args.command:
        case "run":
            return run_task(
                args.task_file,
                args.workspace,
                args.max_iter,
                mock=args.mock,
                model=resolved_model,
            )
        case "list":
            return list_runs(args.workspace)
        case "resume":
            return resume_run(
                args.workspace,
                run_id=args.run_id,
                mock=args.mock,
                model=resolved_model,
            )
        case _:
            return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""CLI entry point for ready-to-work (rtw) architect loop."""

import argparse
import logging
import sys
from pathlib import Path

from rtw.architect import BuilderNode, PlannerNode, ReviewerNode
from rtw.core import Flow, FlowStatus, SharedState
from rtw.llm import CursorAgentClient, MockLLMClient
from rtw.storage import StateStorage


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_architect_flow(llm_client, on_state_change=None) -> Flow:
    """Wire up the Plan -> Build -> Review loop."""
    planner = PlannerNode(llm_client)
    builder = BuilderNode(llm_client)
    reviewer = ReviewerNode(llm_client)

    planner.on("build") >> builder
    builder.on("review") >> reviewer
    reviewer.on("plan") >> planner

    return Flow(start=planner, name="architect", on_state_change=on_state_change)


def run_task(task_file: Path, workspace: Path, max_iterations: int, mock: bool = False) -> int:
    """Execute the architect loop on a task file."""
    logger = logging.getLogger("rtw")

    if not task_file.exists():
        logger.error(f"Task file not found: {task_file}")
        return 1

    task_content = task_file.read_text()
    logger.info(f"Loaded task from: {task_file}")
    logger.info(f"Task length: {len(task_content)} chars")

    storage = StateStorage(workspace)
    logger.info(f"Run ID: {storage.run_id}")
    logger.info(f"State stored in: {storage.base_dir}")

    state = SharedState(
        task_file=str(task_file),
        task_content=task_content,
        workspace=str(workspace),
        max_iterations=max_iterations,
    )

    if mock:
        logger.info("Using mock LLM client for testing")
        llm_client = MockLLMClient(
            responses={
                "architect": '{"summary": "Mock plan", "steps": [{"id": 1, "description": "Test step", "type": "create", "target": "test.py", "details": "Create test file"}], "dependencies": [], "risks": [], "estimated_complexity": "low"}',
                "developer": '{"completed_steps": [{"step_id": 1, "status": "completed", "action_taken": "Created test file", "files_affected": ["test.py"], "notes": "Done"}], "artifacts_created": [{"path": "test.py", "action": "created"}], "issues_encountered": [], "next_steps_suggested": []}',
                "reviewer": '{"verdict": "approve", "score": 95, "summary": "Task completed successfully", "strengths": ["Clean implementation"], "issues": [], "feedback": "", "blocking_reason": null}',
            }
        )
    else:
        llm_client = CursorAgentClient(workspace)

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
        logger.error(f"Flow failed: {e}")
        storage.save(state)
        return 1

    logger.info("=" * 50)
    logger.info("Flow completed")
    logger.info("=" * 50)
    logger.info(f"Final status: {final_state.status.value}")
    logger.info(f"Iterations: {final_state.current_iteration}")
    logger.info(f"Artifacts: {len(final_state.artifacts)}")

    if final_state.status == FlowStatus.COMPLETED:
        logger.info(f"Summary: {final_state.final_summary}")
        return 0
    elif final_state.status == FlowStatus.BLOCKED:
        logger.warning(f"Blocked: {final_state.blocking_reason}")
        return 2
    else:
        logger.warning(f"Ended with status: {final_state.status.value}")
        return 1


def resume_run(workspace: Path, run_id: str | None = None) -> int:
    """Resume a previous run from persisted state."""
    logger = logging.getLogger("rtw")

    if run_id:
        storage = StateStorage(workspace, run_id)
    else:
        storage = StateStorage.get_latest_run(workspace)
        if not storage:
            logger.error("No previous runs found")
            return 1

    state = storage.load()
    if not state:
        logger.error(f"Could not load state from run: {storage.run_id}")
        return 1

    logger.info(f"Resuming run: {storage.run_id}")
    logger.info(f"Status: {state.status.value}, Iteration: {state.current_iteration}")

    logger.info("Resume functionality would continue from this state")
    return 0


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
  rtw run task.md                  # Run architect loop on task.md
  rtw run task.md --max-iter 5     # Limit to 5 iterations
  rtw run task.md --mock           # Test with mock LLM
  rtw list                         # List previous runs
  rtw resume                       # Resume latest run
  rtw resume --run-id 20240101_120000  # Resume specific run
        """,
    )

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
    run_parser.add_argument("--mock", action="store_true", help="Use mock LLM for testing")

    subparsers.add_parser("list", help="List previous runs")

    resume_parser = subparsers.add_parser("resume", help="Resume a previous run")
    resume_parser.add_argument("--run-id", type=str, help="Specific run ID to resume")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "run":
        return run_task(args.task_file, args.workspace, args.max_iter, args.mock)
    elif args.command == "list":
        return list_runs(args.workspace)
    elif args.command == "resume":
        return resume_run(args.workspace, args.run_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())

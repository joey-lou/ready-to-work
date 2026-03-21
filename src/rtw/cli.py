#!/usr/bin/env python3
"""CLI entry point for ready-to-work (rtw) architect loop."""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from rtw import __version__
from rtw.agent import AgentBackend, CursorAgentBackend
from rtw.architect import ExecutorNode, PlannerNode, ReviewerNode
from rtw.core import Flow, FlowStatus, SharedState
from rtw.storage import StateStorage

KNOWN_BACKENDS = frozenset({"cursor", "codex", "claude"})


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_agent(
    model: str | None = None,
    workspace: Path | None = None,
    backend: str = "cursor",
) -> AgentBackend:
    """Factory function for creating agent backends. Exposed for testing."""
    resolved_model = model or os.environ.get("RTW_MODEL")
    return _make_agent_backend(backend, workspace or Path.cwd(), resolved_model)


def _make_agent_backend(backend: str, workspace: Path, model: str | None) -> AgentBackend:
    """Construct the appropriate agent backend."""
    match backend:
        case "cursor":
            return CursorAgentBackend(workspace, model=model)
        case "codex":
            raise NotImplementedError(
                "Codex backend not yet implemented. See src/rtw/agent/codex.py for the stub."
            )
        case "claude":
            raise NotImplementedError(
                "Claude Code backend not yet implemented. See src/rtw/agent/claude.py for the stub."
            )
        case _:
            raise ValueError(f"Unknown backend: {backend}")


def _report_final_status(logger: logging.Logger, final_state: SharedState, run_dir: Path) -> int:
    logger.info("=" * 50)
    logger.info("Flow completed")
    logger.info("=" * 50)
    logger.info("Final status: %s", final_state.status.value)
    logger.info("Iterations: %d", final_state.current_iteration)

    match final_state.status:
        case FlowStatus.COMPLETED:
            summary_path = run_dir / "SUMMARY.md"
            if summary_path.exists():
                logger.info("Summary: %s", summary_path.read_text()[:500].strip())
            return 0
        case FlowStatus.BLOCKED:
            logger.warning("Blocked: %s", final_state.blocking_reason)
            return 2
        case _:
            logger.warning("Ended with status: %s", final_state.status.value)
            return 1


def create_flow(agent: AgentBackend, on_state_change=None) -> Flow:
    """Wire up the Plan -> Execute -> Review loop."""
    planner = PlannerNode(agent)
    executor = ExecutorNode(agent)
    reviewer = ReviewerNode(agent)

    planner.on("execute") >> executor
    executor.on("review") >> reviewer
    reviewer.on("execute") >> executor
    reviewer.on("plan") >> planner

    return Flow(start=planner, name="architect", on_state_change=on_state_change)


_FLOW_RUN_EXCEPTIONS = (OSError, ValueError, TypeError, RuntimeError, KeyError)


def _execute_flow(
    flow: Flow,
    state: SharedState,
    storage: StateStorage,
    logger: logging.Logger,
) -> int:
    """Run a flow with consistent interrupt/error handling and state persistence."""
    try:
        final_state = flow.run(state)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        storage.save(state)
        return 130
    except _FLOW_RUN_EXCEPTIONS as e:
        logger.error("Flow failed: %s", e)
        storage.save(state)
        return 1

    return _report_final_status(logger, final_state, Path(final_state.run_dir))


def run_task(
    task_file: Path,
    workspace: Path,
    max_iterations: int,
    model: str | None = None,
    backend: str = "cursor",
) -> int:
    """Execute the architect loop on a task file."""
    logger = logging.getLogger("rtw")
    workspace = workspace.resolve()

    if not task_file.exists():
        logger.error("Task file not found: %s", task_file)
        return 1

    task_content = task_file.read_text()
    logger.info("Loaded task from: %s", task_file)
    logger.info("Task length: %d chars", len(task_content))

    storage = StateStorage(workspace)
    storage.initialize_task_doc(task_content)
    logger.info("Run ID: %s", storage.run_id)
    logger.info("State stored in: %s", storage.base_dir)

    state = SharedState(
        task_file=str(storage.task_doc),
        task_content=storage.task_doc.read_text(),
        workspace=str(workspace),
        run_dir=str(storage.base_dir),
        run_tmp_dir=str(storage.tmp_dir),
        max_iterations=max_iterations,
    )

    agent = create_agent(model=model, workspace=workspace, backend=backend)
    flow = create_flow(agent, on_state_change=storage.save)
    logger.info("Using %s backend", agent.name)

    logger.info("=" * 50)
    logger.info("Starting architect loop")
    logger.info("=" * 50)

    return _execute_flow(flow, state, storage, logger)


def resume_run(
    workspace: Path,
    run_id: str | None = None,
    model: str | None = None,
    backend: str = "cursor",
) -> int:
    """Resume a previous run from persisted state."""
    logger = logging.getLogger("rtw")
    workspace = workspace.resolve()

    if run_id:
        storage = StateStorage(workspace, run_id)
    else:
        storage = StateStorage.get_latest_run(workspace)
        if not storage:
            logger.error(
                "No previous runs found in %s. Use: rtw resume -w /path/to/project",
                workspace,
            )
            return 1

    state = storage.load()
    if not state:
        logger.error(
            "Could not load state from run %s. Check -w points to the correct project.",
            storage.run_id,
        )
        return 1

    if not state.run_tmp_dir:
        state.run_tmp_dir = str(storage.tmp_dir)
    if not state.run_dir:
        state.run_dir = str(storage.base_dir)

    logger.info("Resuming run: %s", storage.run_id)
    logger.info("Previous status: %s, Iteration: %d", state.status.value, state.current_iteration)

    state.status = FlowStatus.PENDING

    agent = create_agent(model=model, workspace=Path(state.workspace), backend=backend)
    flow = create_flow(agent, on_state_change=storage.save)

    logger.info("=" * 50)
    logger.info("Continuing architect loop")
    logger.info("=" * 50)

    return _execute_flow(flow, state, storage, logger)


def _format_ts(iso_ts: str | None) -> str:
    """Format ISO timestamp for display (e.g. 2026-02-22 13:31)."""
    if not iso_ts:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_ts[:16] if iso_ts else "—"


def list_runs(workspace: Path, max_count: int = 5, reverse: bool = False) -> int:
    """List runs with metadata. Default: last N runs in chronological order (latest last).
    With -r: last N runs in reverse chronological order (newest first, oldest of that window last)."""
    runs = StateStorage.list_runs(workspace)

    if not runs:
        print("No runs found")
        return 0

    recent = runs if reverse else runs[::-1]
    shown = recent[-max_count:]
    total = len(runs)
    if total > max_count:
        print(f"Showing last {max_count} of {total} runs (use -n N for more).\n")
    else:
        print(f"Found {total} run(s):\n")

    for run_id in shown:
        storage = StateStorage(workspace, run_id)
        state = storage.load()
        if state:
            print(f"  {run_id}")
            print(f"    Status:       {state.status.value}")
            print(f"    Iterations:   {state.current_iteration} / {state.max_iterations}")
            print(f"    Updated:      {_format_ts(state.updated_at)}")
            print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ready to work!? - Architect loop for AI-driven development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  rtw run task.md                  # Run architect loop
  rtw run task.md --max-iter 5     # Limit to 5 iterations
  rtw run task.md --backend codex  # Use Codex CLI backend
  rtw list                         # Last N runs, chronological (latest last)
  rtw resume                       # Resume latest run
  rtw resume --run-id 20240101_120000

Backends:
  cursor  - Cursor Agent CLI (default)
  codex   - OpenAI Codex CLI [stub]
  claude  - Claude Code CLI [stub]
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

    def add_common_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--model",
            type=str,
            default=None,
            help="Agent model (e.g. sonnet-4.6). Overrides RTW_MODEL env.",
        )
        subparser.add_argument(
            "--backend",
            type=str,
            default="cursor",
            choices=list(KNOWN_BACKENDS),
            help="Agent backend (default: cursor)",
        )

    run_parser = subparsers.add_parser("run", help="Run architect loop on a task file")
    run_parser.add_argument("task_file", type=Path, help="Path to task.md file")
    run_parser.add_argument("--max-iter", type=int, default=10, help="Max iterations (default: 10)")
    add_common_args(run_parser)

    list_parser = subparsers.add_parser(
        "list",
        help="List previous runs. Default: last N in chronological order (latest last).",
    )
    list_parser.add_argument(
        "-n",
        "--max-count",
        type=int,
        default=5,
        metavar="N",
        help="Show at most N runs (default: 5)",
    )
    list_parser.add_argument(
        "-r",
        "--reverse",
        action="store_true",
        help="Reverse display order",
    )

    resume_parser = subparsers.add_parser("resume", help="Resume a previous run")
    resume_parser.add_argument("--run-id", type=str, help="Specific run ID to resume")
    add_common_args(resume_parser)

    args = parser.parse_args()
    setup_logging(args.verbose)

    model_arg = getattr(args, "model", None)
    backend_arg = getattr(args, "backend", "cursor")

    match args.command:
        case "run":
            return run_task(
                args.task_file,
                args.workspace,
                args.max_iter,
                model=model_arg,
                backend=backend_arg,
            )
        case "list":
            return list_runs(
                args.workspace,
                max_count=args.max_count,
                reverse=args.reverse,
            )
        case "resume":
            return resume_run(
                args.workspace,
                run_id=args.run_id,
                model=model_arg,
                backend=backend_arg,
            )
        case _:
            return 0


if __name__ == "__main__":
    sys.exit(main())

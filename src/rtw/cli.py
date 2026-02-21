#!/usr/bin/env python3
"""CLI entry point for ready-to-work (rtw) architect loop."""

import argparse
import logging
import os
import sys
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


class MockAgentBackend(AgentBackend):
    """Mock backend for testing without real agent calls."""

    def __init__(self):
        # Don't call super().__init__ - we don't need workspace/model/timeout
        self.workspace = Path.cwd()
        self.model = None
        self.timeout = 60

    @property
    def name(self) -> str:
        return "mock"

    # Override high-level methods directly (skip subprocess layer)
    def execute_step(self, step, workspace, context=None):
        from rtw.agent import StepResult, StepStatus

        return StepResult(
            step_id=step.get("id", 0),
            status=StepStatus.COMPLETED,
            description=step.get("description", ""),
            action_taken="Mock action",
            files_changed=[],
        )

    def complete_json(self, prompt, system=None):
        if system and "architect" in system.lower():
            return {
                "summary": "Mock plan",
                "steps": [
                    {
                        "id": 1,
                        "description": "Mock step",
                        "type": "create",
                        "target": "mock.py",
                        "details": "details",
                    }
                ],
                "dependencies": [],
                "risks": [],
                "estimated_complexity": "low",
            }
        if system and "reviewer" in system.lower():
            return {
                "verdict": "approve",
                "score": 90,
                "summary": "Good",
                "strengths": [],
                "issues": [],
                "feedback": "",
                "blocking_reason": None,
            }
        return {"mock": True}

    # Implement abstract methods (not used since we override execute_step/complete_json)
    def _build_exec_command(self, prompt, workspace):
        return ["echo", "mock"]

    def _build_json_command(self, prompt):
        return ["echo", "{}"]

    def _parse_exec_output(self, output, step_id, description):
        from rtw.agent import StepResult, StepStatus

        return StepResult(step_id=step_id, status=StepStatus.COMPLETED, description=description)

    def _parse_json_output(self, output):
        return {}


def create_agent(
    mock: bool = False,
    model: str | None = None,
    workspace: Path | None = None,
    backend: str = "cursor",
) -> AgentBackend:
    """Factory function for creating agent backends. Exposed for testing."""
    if mock:
        return MockAgentBackend()

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


def create_flow(agent: AgentBackend, on_state_change=None) -> Flow:
    """Wire up the Plan -> Execute -> Review loop."""
    planner = PlannerNode(agent)
    executor = ExecutorNode(agent)
    reviewer = ReviewerNode(agent)

    planner.on("build") >> executor
    executor.on("review") >> reviewer
    reviewer.on("plan") >> planner

    return Flow(start=planner, name="architect", on_state_change=on_state_change)


def run_task(
    task_file: Path,
    workspace: Path,
    max_iterations: int,
    model: str | None = None,
    backend: str = "cursor",
    mock: bool = False,
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

    agent = create_agent(mock=mock, model=model, workspace=workspace, backend=backend)
    flow = create_flow(agent, on_state_change=storage.save)
    logger.info("Using %s backend", agent.name)

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
    model: str | None = None,
    backend: str = "cursor",
    mock: bool = False,
) -> int:
    """Resume a previous run from persisted state."""
    logger = logging.getLogger("rtw")

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

    logger.info("Resuming run: %s", storage.run_id)
    logger.info("Previous status: %s, Iteration: %d", state.status.value, state.current_iteration)

    state.status = FlowStatus.PENDING

    agent = create_agent(mock=mock, model=model, workspace=Path(state.workspace), backend=backend)
    flow = create_flow(agent, on_state_change=storage.save)

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
  rtw run task.md                  # Run architect loop
  rtw run task.md --max-iter 5     # Limit to 5 iterations
  rtw run task.md --backend codex  # Use Codex CLI backend
  rtw list                         # List previous runs
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
        subparser.add_argument(
            "--mock",
            action="store_true",
            help="Use mock agent (for testing)",
        )

    run_parser = subparsers.add_parser("run", help="Run architect loop on a task file")
    run_parser.add_argument("task_file", type=Path, help="Path to task.md file")
    run_parser.add_argument("--max-iter", type=int, default=10, help="Max iterations (default: 10)")
    add_common_args(run_parser)

    subparsers.add_parser("list", help="List previous runs")

    resume_parser = subparsers.add_parser("resume", help="Resume a previous run")
    resume_parser.add_argument("--run-id", type=str, help="Specific run ID to resume")
    add_common_args(resume_parser)

    args = parser.parse_args()
    setup_logging(args.verbose)

    model_arg = getattr(args, "model", None)
    backend_arg = getattr(args, "backend", "cursor")
    mock_arg = getattr(args, "mock", False)

    resolved_model = model_arg or os.environ.get("RTW_MODEL")

    match args.command:
        case "run":
            return run_task(
                args.task_file,
                args.workspace,
                args.max_iter,
                model=resolved_model,
                backend=backend_arg,
                mock=mock_arg,
            )
        case "list":
            return list_runs(args.workspace)
        case "resume":
            return resume_run(
                args.workspace,
                run_id=args.run_id,
                model=resolved_model,
                backend=backend_arg,
                mock=mock_arg,
            )
        case _:
            return 0


if __name__ == "__main__":
    sys.exit(main())

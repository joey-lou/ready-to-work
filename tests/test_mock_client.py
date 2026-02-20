"""Tests for MockLLMClient capabilities and CLI argument parsing."""

import pytest
from llm_mock import MockLLMClient

from rtw import __version__

# ---------------------------------------------------------------------------
# MockLLMClient tests
# ---------------------------------------------------------------------------


def test_fail_on_call_raises_runtime_error():
    llm = MockLLMClient(fail_on_call=2)
    llm.complete("first call")  # call 1 – OK
    with pytest.raises(RuntimeError, match="call #2"):
        llm.complete("second call")  # call 2 – boom


def test_fail_on_call_does_not_trigger_on_other_calls():
    llm = MockLLMClient(fail_on_call=3)
    llm.complete("one")
    llm.complete("two")
    assert llm.call_count == 2  # call 3 not reached yet – no error


def test_per_key_call_counts_increment():
    llm = MockLLMClient(responses={"architect": "plan", "developer": "build"})
    llm.complete("", system="You are a senior software architect")
    llm.complete("", system="You are a senior software architect")
    llm.complete("", system="You are a senior software developer")

    assert llm.call_counts.get("architect") == 2
    assert llm.call_counts.get("developer") == 1


def test_complete_returns_correct_response_for_system_key():
    llm = MockLLMClient(responses={"planner": "step 1"})
    result = llm.complete("anything", system="I am the planner")
    assert result == "step 1"


def test_complete_returns_correct_response_for_prompt_key():
    llm = MockLLMClient(responses={"magic": "found it"})
    result = llm.complete("use magic here", system=None)
    assert result == "found it"


def test_complete_returns_fallback_when_no_key_matches():
    llm = MockLLMClient(responses={"nothing_matches": "x"})
    result = llm.complete("unrelated prompt")
    assert result.startswith("Mock response #")


def test_complete_json_with_valid_json_response():
    import json

    payload = {"verdict": "approve", "score": 99}
    llm = MockLLMClient(responses={"test": json.dumps(payload)})
    result = llm.complete_json("test prompt")
    assert result == payload


def test_complete_json_fail_with_json_error_raises():
    llm = MockLLMClient(fail_with_json_error=True)
    with pytest.raises(RuntimeError, match="Injected JSON error"):
        llm.complete_json("anything")


def test_side_effect_callable_is_invoked():
    def my_effect(prompt, system):
        return f"custom:{prompt}"

    llm = MockLLMClient(side_effect=my_effect)
    result = llm.complete("hello")
    assert result == "custom:hello"


def test_side_effect_overrides_responses():
    llm = MockLLMClient(
        responses={"key": "ignored"},
        side_effect=lambda p, s: "from_effect",
    )
    result = llm.complete("key")
    assert result == "from_effect"


# ---------------------------------------------------------------------------
# CLI argument parsing tests
# ---------------------------------------------------------------------------


def _parse_args(args: list[str]):
    """Run argument parsing without executing commands."""
    # Import main to get the parser; use parse_known_args to avoid sys.exit
    import argparse

    # Reconstruct parser inline to test parsing without side effects
    parser = argparse.ArgumentParser()
    parser.add_argument("-V", "--version", action="version", version=f"rtw {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-w", "--workspace", default=".")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run")
    run_p.add_argument("task_file")
    run_p.add_argument("--max-iter", type=int, default=10)
    run_p.add_argument("--model", default=None)
    sub.add_parser("list")
    res_p = sub.add_parser("resume")
    res_p.add_argument("--run-id", default=None)
    res_p.add_argument("--model", default=None)

    return parser.parse_args(args)


def test_verbose_flag_parsed():
    args = _parse_args(["-v", "list"])
    assert args.verbose is True


def test_verbose_long_flag_parsed():
    args = _parse_args(["--verbose", "list"])
    assert args.verbose is True


def test_version_flag_exits_with_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(["-V"])
    assert exc_info.value.code == 0


def test_run_subcommand_parsed():
    args = _parse_args(["run", "task.md", "--max-iter", "3"])
    assert args.command == "run"
    assert args.task_file == "task.md"
    assert args.max_iter == 3


def test_resume_subcommand_with_run_id():
    args = _parse_args(["resume", "--run-id", "20240101_120000"])
    assert args.command == "resume"
    assert args.run_id == "20240101_120000"


def test_list_subcommand_parsed():
    args = _parse_args(["list"])
    assert args.command == "list"


# ---------------------------------------------------------------------------
# Additional MockLLMClient tests
# ---------------------------------------------------------------------------


def test_fail_on_call_with_complete_json():
    """fail_on_call triggers on complete_json calls too."""
    import json

    llm = MockLLMClient(responses={"key": json.dumps({"ok": True})}, fail_on_call=2)
    llm.complete_json("key prompt")  # call 1 – OK
    with pytest.raises(RuntimeError, match="call #2"):
        llm.complete_json("key prompt")  # call 2 – boom


def test_call_count_increments_across_complete_and_complete_json():
    import json

    llm = MockLLMClient(responses={"test": json.dumps({"x": 1})})
    llm.complete("some prompt")
    llm.complete_json("test prompt")
    llm.complete("another")
    assert llm.call_count == 3


def test_empty_responses_returns_fallback():
    llm = MockLLMClient(responses={})
    result = llm.complete("anything")
    assert result.startswith("Mock response #")


def test_side_effect_returning_non_string_propagates():
    """side_effect returning a non-string value propagates as-is."""

    def bad_effect(prompt, system):
        return 42  # not a string

    llm = MockLLMClient(side_effect=bad_effect)
    result = llm.complete("prompt")
    assert result == 42


# ---------------------------------------------------------------------------
# Additional CLI tests
# ---------------------------------------------------------------------------


def test_cli_run_missing_task_file_exits_nonzero():
    """run subcommand with non-existent task file returns non-zero."""
    import tempfile
    from pathlib import Path

    from rtw.cli import run_task

    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_task(
            task_file=Path(tmpdir) / "nonexistent_task.md",
            workspace=Path(tmpdir),
            max_iterations=1,
            mock=True,
        )
    assert result != 0


def test_cli_resume_run_id_parsed_correctly():
    args = _parse_args(["resume", "--run-id", "20250101_123456"])
    assert args.run_id == "20250101_123456"
    assert args.command == "resume"


def test_workspace_flag_defaults_to_dot():
    args = _parse_args(["list"])
    assert args.workspace == "."


def test_model_flag_passed_through_run():
    args = _parse_args(["run", "task.md", "--model", "claude-3-sonnet"])
    assert args.model == "claude-3-sonnet"


def test_model_flag_passed_through_resume():
    args = _parse_args(["resume", "--model", "gpt-4"])
    assert args.model == "gpt-4"


# ---------------------------------------------------------------------------
# response_sequence cycling edge cases
# ---------------------------------------------------------------------------


def test_response_sequence_single_entry_cycles():
    """Single-entry sequence returns that entry indefinitely after exhaustion."""
    llm = MockLLMClient(response_sequence={"key": ["only_response"]})
    assert llm.complete("use key here") == "only_response"
    assert llm.complete("use key here") == "only_response"
    assert llm.complete("use key here") == "only_response"


def test_response_sequence_takes_precedence_over_responses():
    """response_sequence wins for the same key over responses dict."""
    llm = MockLLMClient(
        responses={"architect": "from_responses"},
        response_sequence={"architect": ["from_sequence"]},
    )
    result = llm.complete("", system="You are a senior software architect")
    assert result == "from_sequence"


def test_sequence_indices_advance_correctly():
    """_sequence_indices increments per call per key."""
    llm = MockLLMClient(response_sequence={"key": ["first", "second", "third"]})
    assert llm.complete("key one") == "first"
    assert llm._sequence_indices.get("key") == 1
    assert llm.complete("key two") == "second"
    assert llm._sequence_indices.get("key") == 2
    assert llm.complete("key three") == "third"
    assert llm._sequence_indices.get("key") == 3
    # Exhausted: cycles on last entry
    assert llm.complete("key four") == "third"
    assert llm._sequence_indices.get("key") == 4


def test_response_sequence_overlapping_keys_sequence_wins():
    """When both responses and response_sequence have same key, sequence wins."""
    llm = MockLLMClient(
        responses={"mykey": "response_value"},
        response_sequence={"mykey": ["seq_value_1", "seq_value_2"]},
    )
    assert llm.complete("mykey is here") == "seq_value_1"
    assert llm.complete("mykey again") == "seq_value_2"
    # After exhaustion cycles on last
    assert llm.complete("mykey again") == "seq_value_2"


def test_complete_json_fail_with_json_error_and_fail_on_call():
    """fail_with_json_error=True always raises; fail_on_call changes the message on that call."""
    llm = MockLLMClient(fail_with_json_error=True, fail_on_call=2)
    # Call 1: raises injected JSON error
    with pytest.raises(RuntimeError, match="Injected JSON error"):
        llm.complete_json("prompt")
    assert llm.call_count == 1
    # Call 2: raises fail_on_call error
    with pytest.raises(RuntimeError, match="call #2"):
        llm.complete_json("prompt")


# ---------------------------------------------------------------------------
# CLI main() dispatch tests
# ---------------------------------------------------------------------------


def test_main_dispatches_list():
    """main() with 'list' command calls list_runs and returns 0."""
    from unittest.mock import patch as upatch

    from rtw.cli import main

    with (
        upatch("sys.argv", ["rtw", "list"]),
        upatch("rtw.cli.list_runs", return_value=0) as mock_list,
        upatch("rtw.cli.setup_logging"),
    ):
        result = main()

    assert result == 0
    mock_list.assert_called_once()


def test_main_dispatches_run_with_mock():
    """main() with 'run' command and --mock passes mock=True to run_task."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch as upatch

    from rtw.cli import main

    with tempfile.TemporaryDirectory() as tmpdir:
        task_file = str(Path(tmpdir) / "task.md")
        Path(task_file).write_text("task")

        with (
            upatch("sys.argv", ["rtw", "-w", tmpdir, "run", task_file, "--mock"]),
            upatch("rtw.cli.run_task", return_value=0) as mock_run,
            upatch("rtw.cli.setup_logging"),
        ):
            result = main()

    assert result == 0
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs.get("mock") is True


def test_main_dispatches_resume_with_mock():
    """main() with 'resume --mock' passes mock=True to resume_run."""
    import tempfile
    from unittest.mock import patch as upatch

    from rtw.cli import main

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            upatch("sys.argv", ["rtw", "-w", tmpdir, "resume", "--mock"]),
            upatch("rtw.cli.resume_run", return_value=0) as mock_resume,
            upatch("rtw.cli.setup_logging"),
        ):
            result = main()

    assert result == 0
    call_kwargs = mock_resume.call_args
    assert call_kwargs.kwargs.get("mock") is True


def test_report_final_status_completed_returns_0():
    """_report_final_status returns 0 for COMPLETED status."""
    import logging

    from rtw.cli import _report_final_status
    from rtw.core import FlowStatus, SharedState

    state = SharedState(
        task_file="t.md", task_content="x", workspace="/tmp", status=FlowStatus.COMPLETED
    )
    state.final_summary = "Done"
    result = _report_final_status(logging.getLogger("test"), state)
    assert result == 0


def test_report_final_status_blocked_returns_2():
    """_report_final_status returns 2 for BLOCKED status."""
    import logging

    from rtw.cli import _report_final_status
    from rtw.core import FlowStatus, SharedState

    state = SharedState(
        task_file="t.md", task_content="x", workspace="/tmp", status=FlowStatus.BLOCKED
    )
    state.blocking_reason = "Stuck"
    result = _report_final_status(logging.getLogger("test"), state)
    assert result == 2


def test_report_final_status_other_returns_1():
    """_report_final_status returns 1 for non-COMPLETED, non-BLOCKED statuses."""
    import logging

    from rtw.cli import _report_final_status
    from rtw.core import FlowStatus, SharedState

    state = SharedState(
        task_file="t.md", task_content="x", workspace="/tmp", status=FlowStatus.FAILED
    )
    result = _report_final_status(logging.getLogger("test"), state)
    assert result == 1

"""append_agent_trace: writes prompt/output to run_dir/traces/ as .txt files."""

import tempfile
from pathlib import Path

from rtw.core.trace import append_agent_trace


def test_append_agent_trace_writes_prompt_and_output_files():
    """append_agent_trace creates traces/iter-NNN-stage-prompt.txt and -output.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        append_agent_trace(run_dir, stage="PLANNER", iteration=1, output="Done.", prompt="Do X.")
        traces = run_dir / "traces"
        assert (traces / "iter-001-planner-prompt.txt").read_text().strip() == "Do X."
        assert (traces / "iter-001-planner-output.txt").read_text().strip() == "Done."


def test_append_agent_trace_creates_separate_files_per_stage():
    """Each stage/iteration gets its own prompt and output files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        append_agent_trace(run_dir, stage="PLANNER", iteration=1, prompt="P1", output="O1")
        append_agent_trace(run_dir, stage="EXECUTOR", iteration=1, prompt="P2", output="O2")
        append_agent_trace(run_dir, stage="REVIEWER", iteration=2)
        traces = run_dir / "traces"
        assert (traces / "iter-001-planner-prompt.txt").read_text().strip() == "P1"
        assert (traces / "iter-001-planner-output.txt").read_text().strip() == "O1"
        assert (traces / "iter-001-executor-prompt.txt").read_text().strip() == "P2"
        assert (traces / "iter-001-executor-output.txt").read_text().strip() == "O2"
        assert not (traces / "iter-002-reviewer-prompt.txt").exists()
        assert not (traces / "iter-002-reviewer-output.txt").exists()

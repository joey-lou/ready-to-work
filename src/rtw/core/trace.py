"""Write agent prompt and output to run_dir/traces/ as individual .txt files."""

from pathlib import Path

from .paths import TRACES_DIR


def append_agent_trace(
    run_dir: str | Path,
    *,
    stage: str,
    iteration: int,
    output: str | None = None,
    prompt: str | None = None,
) -> None:
    """Write one stage trace to traces/iter-NNN-{stage}-prompt.txt and -output.txt."""
    base = Path(run_dir) / TRACES_DIR
    base.mkdir(parents=True, exist_ok=True)
    stage_lower = stage.lower()
    prefix = f"iter-{iteration:03d}-{stage_lower}"
    if prompt is not None:
        (base / f"{prefix}-prompt.txt").write_text(prompt.strip() + "\n", encoding="utf-8")
    if output is not None:
        (base / f"{prefix}-output.txt").write_text(output.strip() + "\n", encoding="utf-8")

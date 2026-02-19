"""State persistence for rtw runs."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from rtw.core.state import SharedState

logger = logging.getLogger(__name__)


class StateStorage:
    """
    Persists SharedState to disk for resumability and debugging.

    Storage structure:
    .rtw/
    ├── runs/
    │   ├── {run_id}/
    │   │   ├── state.json          # Current state snapshot
    │   │   ├── history/
    │   │   │   ├── iter_001.json   # Per-iteration snapshots
    │   │   │   ├── iter_002.json
    │   │   │   └── ...
    │   │   └── artifacts.json      # Artifact manifest
    """

    def __init__(self, workspace: str | Path, run_id: str | None = None):
        self.workspace = Path(workspace)
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base_dir = self.workspace / ".rtw" / "runs" / self.run_id
        self.history_dir = self.base_dir / "history"

        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state_file(self) -> Path:
        return self.base_dir / "state.json"

    def save(self, state: SharedState) -> None:
        """Save current state to disk."""
        state.touch()
        data = state.to_dict()

        self.state_file.write_text(json.dumps(data, indent=2))
        logger.debug(f"State saved to {self.state_file}")

        if state.current_iteration > 0:
            iter_file = self.history_dir / f"iter_{state.current_iteration:03d}.json"
            record = state.current_record()
            if record:
                iter_data = {
                    "iteration": record.iteration,
                    "plan": record.plan,
                    "build_result": record.build_result,
                    "review_result": record.review_result,
                    "timestamp": record.timestamp,
                    "status": state.status.value,
                }
                iter_file.write_text(json.dumps(iter_data, indent=2))

    def load(self) -> SharedState | None:
        """Load state from disk if exists."""
        if not self.state_file.exists():
            return None

        try:
            data = json.loads(self.state_file.read_text())
            return SharedState.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None

    def list_iterations(self) -> list[dict[str, Any]]:
        """List all iteration snapshots."""
        iterations = []
        for f in sorted(self.history_dir.glob("iter_*.json")):
            try:
                iterations.append(json.loads(f.read_text()))
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")
        return iterations

    @classmethod
    def list_runs(cls, workspace: str | Path) -> list[str]:
        """List all run IDs in a workspace."""
        runs_dir = Path(workspace) / ".rtw" / "runs"
        if not runs_dir.exists():
            return []
        return sorted([d.name for d in runs_dir.iterdir() if d.is_dir()], reverse=True)

    @classmethod
    def get_latest_run(cls, workspace: str | Path) -> "StateStorage | None":
        """Get storage for the most recent run."""
        runs = cls.list_runs(workspace)
        if not runs:
            return None
        return cls(workspace, runs[0])

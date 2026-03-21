"""Shared filesystem helpers for run-directory documents."""

import json
from pathlib import Path
from typing import Any


def read_text_if_exists(path: Path) -> str:
    """Return file contents or empty string if missing."""
    return path.read_text() if path.exists() else ""


def read_json_dict(path: Path) -> dict[str, Any]:
    """Parse JSON object from path; return {} if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def relpath_or_abs(path: Path, base: Path) -> str:
    """Return POSIX-style path relative to base, or absolute string fallback."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)

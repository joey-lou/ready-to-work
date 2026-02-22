#!/usr/bin/env python3
"""Fail if any Python file exceeds the max line count. Used in CI and pre-commit."""

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Python files do not exceed max lines.")
    parser.add_argument(
        "--max-lines",
        type=int,
        default=500,
        help="Maximum lines per file (default: 500)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["src", "tests"],
        help="Directories or files to check (default: src tests)",
    )
    args = parser.parse_args()

    root = Path.cwd()
    exceeded: list[tuple[Path, int]] = []

    for path_arg in args.paths:
        p = root / path_arg
        if p.is_file() and p.suffix == ".py":
            files = [p]
        elif p.is_dir():
            files = sorted(p.rglob("*.py"))
        else:
            continue
        for f in files:
            line_count = len(f.read_text().splitlines())
            if line_count > args.max_lines:
                exceeded.append((f, line_count))

    if not exceeded:
        return 0
    for path, count in exceeded:
        print(f"{path}: {count} lines (max {args.max_lines})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

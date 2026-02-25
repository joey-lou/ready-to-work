# AGENTS.md

## Cursor Cloud specific instructions

This is a pure Python CLI project (`ready-to-work` / `rtw`). No external services, databases, or Docker are needed.

### Prerequisites

- Python 3.11+
- `uv` package manager (install via `curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Development commands

Standard commands are documented in `README.md § Development`. Quick reference:

| Task | Command |
|------|---------|
| Install deps | `uv sync` |
| Run tests | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format check | `uv run ruff format --check .` |
| CLI help | `uv run rtw --help` |

### Caveats

- The `rtw run` command requires an external agent backend CLI (e.g. `cursor-agent`, `codex`, `claude`) to be installed and authenticated. Tests mock these backends, so no agent CLI is needed to run the test suite.
- Version is derived from git tags via `hatch-vcs`. In a dev checkout without tags, the version will show as a dev version (e.g. `0.0.0a3.dev2+g...`).
- `uv` must be on `PATH`. After install, ensure `$HOME/.local/bin` is in `PATH`.

# ready-to-work (rtw)

[![PyPI version](https://img.shields.io/pypi/v/ready-to-work.svg)](https://pypi.org/project/ready-to-work/)
[![Python versions](https://img.shields.io/pypi/pyversions/ready-to-work.svg)](https://pypi.org/project/ready-to-work/)
[![License](https://img.shields.io/pypi/l/ready-to-work.svg)](https://github.com/joey-lou/ready-to-work/blob/main/LICENSE)
[![CI](https://github.com/joey-lou/ready-to-work/actions/workflows/ci.yml/badge.svg)](https://github.com/joey-lou/ready-to-work/actions/workflows/ci.yml)

Plan → Execute → Review loop for AI-driven development. Unlike simple chat, rtw orchestrates an **agentic loop** where the AI actually executes code changes step-by-step.

## Key Features

- **Step-by-step execution**: Each plan step runs individually with its own timeout, enabling early abort on failures and better error attribution
- **Swappable backends**: Cursor Agent (default), Codex CLI, Claude Code (stubs ready)
- **Persistent state**: Interrupt and resume runs, inspect intermediate results in `.rtw/runs/`
- **Lessons learned**: Cumulative memory across iterations helps the agent avoid repeating mistakes

## Installation

```bash
pip install ready-to-work
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install ready-to-work
```

**Prerequisites:** [Cursor Agent CLI](https://cursor.com/docs/cli) (authenticated), Python 3.11+.

## Usage

```bash
rtw run task.md                      # Run architect loop
rtw run task.md --max-iter 5         # Limit iterations
rtw run task.md --model sonnet-4.6   # Override model
rtw run task.md --backend codex      # Use different agent backend
rtw list                             # List runs
rtw resume                           # Resume latest run
```

### Agent Backends

| Backend  | CLI               | Status                          |
| -------- | ----------------- | ------------------------------- |
| `cursor` | `cursor-agent -p` | ✅ Implemented                  |
| `codex`  | `codex`           | 🔧 Stub (contributions welcome) |
| `claude` | `claude`          | 🔧 Stub (contributions welcome) |

## Development

```bash
git clone https://github.com/joey-lou/ready-to-work.git
cd ready-to-work
uv sync
uv run pre-commit install
```

Run tests and linting:

```bash
uv run pytest
uv run ruff check . && uv run ruff format .
```

## Releasing

Version is derived from git tags via [hatch-vcs](https://github.com/ofek/hatch-vcs). To release:

```bash
git tag v0.3.0 && git push --tags
```

This triggers the [release workflow](.github/workflows/release.yml), which publishes to [PyPI](https://pypi.org/project/ready-to-work/) and creates a [GitHub Release](https://github.com/joey-lou/ready-to-work/releases).

## License

[MIT](LICENSE)

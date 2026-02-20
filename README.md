# ready-to-work (rtw)

Plan → Build → Review loop for AI-driven development. Uses [Cursor Agent CLI](https://cursor.com/docs/cli) as the default backend.

## Installation

```bash
uv tool install git+https://github.com/joey-lou/ready-to-work.git
```

**Prerequisites:** [uv](https://docs.astral.sh/uv/), [Cursor Agent CLI](https://cursor.com/docs/cli) (authenticated), Python 3.11+.

## Usage

```bash
rtw run task.md              # Run architect loop (default model: sonnet-4.6)
rtw run task.md --max-iter 5
rtw run task.md --model gpt-4o  # Override model (must be a known-valid model)
rtw list                     # List runs
rtw resume                   # Resume latest run (use -w /path/to/project if needed)
```

## Development

```bash
uv tool install --editable .   # Pick up code changes without reinstalling
uv sync
uv run python -m pytest
uv run ruff check . && uv run ruff format .
```

Pre-commit runs ruff and pytest on commit:

```bash
uv run pre-commit install
```

## License

MIT

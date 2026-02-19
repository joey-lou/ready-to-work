# ready-to-work (rtw)

Architect loop framework for AI-driven development. Implements a **Plan → Build → Review** cycle that iterates until a task is complete, blocked, or max iterations reached.

Uses [Cursor Agent CLI](https://cursor.com/docs/cli) as the default LLM backend.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       rtw                               │
├─────────────────────────────────────────────────────────┤
│  task.md ──▶ [Planner] ──▶ [Builder] ──▶ [Reviewer]    │
│                  ▲                            │         │
│                  └────── iterate ─────────────┘         │
│                                               │         │
│                          ┌────────────────────┤         │
│                          ▼                    ▼         │
│                      [COMPLETE]           [BLOCKED]     │
└─────────────────────────────────────────────────────────┘
```

## Installation

### Using uv (recommended)

```bash
# Install uv if you haven't
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Option A: Install as a global tool (run from anywhere)

```bash
# Install directly from the repo
uv tool install git+https://github.com/joey-lou/ready-to-work.git

# Or from a local clone
git clone https://github.com/joey-lou/ready-to-work.git
uv tool install ./ready-to-work

# Now rtw is available globally
rtw --help
```

This installs `rtw` in an isolated environment and adds it to your PATH (`~/.local/bin`).

#### Option B: Clone and run with uv

```bash
git clone https://github.com/joey-lou/ready-to-work.git
cd ready-to-work
uv sync

# Run rtw (must be in repo directory)
uv run rtw --help
```

### Using pip

```bash
pip install ready-to-work
```

### Using pipx

```bash
pipx install ready-to-work
```

### From source

```bash
git clone https://github.com/joey-lou/ready-to-work.git
cd ready-to-work
pip install -e .
```

## Prerequisites

1. **Cursor CLI** - Install from [cursor.com](https://cursor.com) and authenticate:
   ```bash
   cursor agent login
   cursor agent status  # Verify authentication
   ```

2. **Python 3.11+**

## Quick Start

```bash
# Create a task file
cat > my_task.md << 'EOF'
# Task: Hello World API

Create a simple FastAPI app with one endpoint that returns {"message": "hello"}.
EOF

# Run the architect loop
rtw run my_task.md

# Or with options
rtw run my_task.md --max-iter 5 -v
```

> **Note**: If you installed with `uv sync` instead of `uv tool install`, prefix commands with `uv run` (e.g., `uv run rtw run my_task.md`).

## Usage

### Run a task

```bash
# Basic usage
rtw run task.md

# With custom iteration limit
rtw run task.md --max-iter 5

# Verbose logging
rtw -v run task.md

# Test with mock LLM (no API calls)
rtw run task.md --mock
```

### Manage runs

```bash
# List previous runs
rtw list

# Resume latest run
rtw resume

# Resume specific run
rtw resume --run-id 20240101_120000
```

## State Persistence

All runs are persisted to `.rtw/runs/{run_id}/`:

```
.rtw/
└── runs/
    └── 20240101_120000/
        ├── state.json          # Current state snapshot
        └── history/
            ├── iter_001.json   # Per-iteration snapshots
            ├── iter_002.json
            └── ...
```

## Creating Tasks

Create a markdown file describing your task:

```markdown
# Task: Create a REST API

## Requirements
- FastAPI-based REST API
- Endpoints for CRUD operations on "items"
- SQLite database with SQLAlchemy
- Pydantic models for validation

## Constraints
- Python 3.11+
- No external auth (simple API keys)

## Success Criteria
- All endpoints return proper JSON
- Error handling with appropriate status codes
- Basic tests included
```

## Flow States

| State | Description |
|-------|-------------|
| `pending` | Initial state |
| `planning` | Generating implementation plan |
| `building` | Executing the plan |
| `reviewing` | Evaluating results |
| `completed` | Task finished successfully |
| `blocked` | Needs human intervention |
| `failed` | Unrecoverable error |

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=rtw

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

### Building

```bash
# Build wheel and sdist
uv build

# Output in dist/
ls dist/
```

### Releasing

Releases are automated via GitHub Actions on tag push:

```bash
git tag v0.1.0
git push origin v0.1.0
```

This will:
1. Run tests
2. Build wheel and sdist
3. Publish to PyPI
4. Create GitHub release

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `CURSOR_API_KEY` | API key for Cursor agent (optional if logged in) |

### CLI Options

```
rtw [OPTIONS] COMMAND

Options:
  -v, --verbose       Enable debug logging
  -w, --workspace     Workspace directory (default: cwd)

Commands:
  run       Run architect loop on a task file
  list      List previous runs  
  resume    Resume a previous run
```

## License

MIT

# RTW Architecture

Target-state architecture for `ready-to-work` (rtw) — the agentic Plan → Execute → Review loop for AI-driven development.

## Overview

RTW orchestrates an AI coding agent through a structured loop: a **Planner** breaks a task into steps, an **Executor** implements one step at a time, and a **Reviewer** verifies the work. Each role is a separate agent invocation with a focused prompt. The loop repeats until the plan is complete, a blocking issue is hit, or the iteration limit is reached.

All context lives in markdown files and `state.json` under `.rtw/runs/<run_id>/`. The Python orchestrator manages routing, persistence, and validation — not content.

```
                    ┌──────────┐
                    │ Planner  │
                    └────┬─────┘
                         │ writes PLAN.md, SUBTASK.md
                         │ sets plan_status
                         ▼
           ┌─────────────────────────────┐
           │        Gatekeeper           │
           │  validate → retry if needed │
           └─────────────┬───────────────┘
                         │
              ┌──────────▼──────────┐
              │      Executor       │
              │  implements step    │
              │  in workspace       │
              └──────────┬──────────┘
                         │ tracks changed files
                         ▼
              ┌──────────────────────┐
              │      Reviewer        │
              │  checks acceptance   │
              │  criteria against    │
              │  changed files       │
              └──────────┬───────────┘
                         │
           ┌─────────────▼───────────────┐
           │        Gatekeeper           │
           │  validate → retry if needed │
           └─────────────┬───────────────┘
                         │
                 ┌───────┴────────┐
                 │                │
              PASSED           REVISE
                 │                │
                 ▼                ▼
             Planner          Executor
           (next step)      (fix issues)
```

## Module Layout

```
src/rtw/
├── cli.py                    # CLI entry: run, list, resume
├── agent/                    # Agent backends (swappable)
│   ├── base.py               # AgentBackend ABC, SubprocessAgentBackend
│   ├── cursor.py             # Cursor Agent CLI
│   ├── codex.py              # OpenAI Codex CLI (stub)
│   └── claude.py             # Claude Code CLI (stub)
├── architect/                # The three loop nodes
│   ├── planner.py            # PlannerNode — maintains plan, writes subtasks
│   ├── executor.py           # ExecutorNode — runs subtask in workspace
│   ├── reviewer.py           # ReviewerNode — verifies work against criteria
│   └── prompts.py            # Prompt templates (PLANNER, EXECUTOR, REVIEWER)
├── core/
│   ├── flow.py               # Flow orchestrator — routing, iteration limits
│   ├── nodes.py              # Node ABC — prep/exec/post lifecycle
│   ├── state.py              # SharedState, FlowStatus, PlanStatus, SubtaskStatus
│   ├── paths.py              # Canonical run-directory paths
│   ├── trace.py              # Agent prompt/output trace logging
│   ├── changes.py            # ChangeTracker — git-first, snapshot fallback
│   ├── io.py                 # read_text_if_exists, read_json_dict
│   └── gatekeeper.py         # Post-step validation and retry
└── storage/
    └── persistence.py        # StateStorage — state.json, history snapshots
```

## Node Lifecycle

Every node follows `prep() → exec() → post()`:

1. **prep(state)** — Read shared state and run-directory files; build context for the agent.
2. **exec(prep_result)** — Call the agent backend with a prompt. The agent edits files in the workspace and/or run directory. Returns a uniform dict: `success`, `output`, `error`, `prompt` (the exact string sent to the agent — used for traces and retries).
3. **post(state, prep_result, exec_result)** — Read agent outputs, **run the gatekeeper** (validate + retry if needed), update shared state, return a routing action.

`Node.increments_iteration` (default `False`): when `True`, the flow increments `current_iteration` before that node and applies the planning-round limit.

The `post()` method is the enforcement point. It runs deterministic validation on every agent output — the agent cannot skip it.

## Document Schema

All documents live under `.rtw/runs/<run_id>/`. The agent writes them; the orchestrator validates them.

### TASK.md

Created once at run start (copied from the user's task file). Read-only during the loop.

### PLAN.md

Written and maintained by the Planner each iteration.

```markdown
# Plan: <title>

## Steps
1. **Step name** — description  ✓
2. **Step name** — description  (active)
3. **Step name** — description

## Lessons
- <insight from a past REVISE cycle>
- <another insight>
```

**Required sections (only these two top-level `##` headings in PLAN.md):**
- `## Steps` — numbered list with completion markers (✓). At least one step.
- `## Lessons` — accumulates insights from failed reviews. May be empty on first iteration but the heading must exist.

Do not add other top-level sections (e.g. `## Goal`, `## Status`). Put extra context inside step text or as bullet lines under `## Lessons` so parsers and validators stay stable.

### SUBTASK.md

Written by the Planner (instructions + acceptance criteria). Updated by the Reviewer (marks criteria, adds review findings).

**After Planner writes it:**

```markdown
# Subtask: <step name>

<instructions for the executor>

## Acceptance criteria
- [ ] criterion 1
- [ ] criterion 2
```

**After Reviewer updates it:**

```markdown
# Subtask: <step name>

<instructions for the executor>

## Acceptance criteria
- [x] criterion 1
- [ ] criterion 2 — missing error handling for 404

## Review
Brief findings here.
```

**Required sections:**
- `## Acceptance criteria` — at least one checklist item (`- [ ]` or `- [x]`).
- `## Review` — required after the reviewer runs (exact heading on its own line: `## Review`, not `## Review section` or similar). Contains findings.

### SUMMARY.md

Written by the Planner when all steps are complete (`plan_status: COMPLETED`). Signals the end of the loop.

### state.json

Machine-readable routing state. Both the orchestrator and the agent read/write it.

```json
{
  "workspace": "/path/to/project",
  "run_dir": ".rtw/runs/20260316_213038",
  "run_tmp_dir": ".rtw/runs/20260316_213038/tmp",
  "status": "PENDING",
  "plan_status": "IN_PROGRESS",
  "subtask_status": "DRAFT",
  "current_iteration": 1,
  "max_iterations": 10,
  "blocking_reason": null,
  "files_changed": [{"path": "src/main.py", "action": "modified"}],
  "updated_at": "2026-03-16T21:30:38"
}
```

`workspace` stays absolute (anchor). `run_dir` and `run_tmp_dir` are stored **relative to `workspace`** so moving the project directory and updating `workspace` (or resuming with `-w` pointed at the new root) can still resolve the run folder. Older `state.json` files may still have absolute `run_dir` / `run_tmp_dir`; those load as before.

**Agent-writable fields (per stage):**
- Planner sets: `plan_status` (`IN_PROGRESS` | `COMPLETED` | `BLOCKED`), `blocking_reason`
- Reviewer sets: `subtask_status` (`REVISE` | `PASSED` | `BLOCKED`), `blocking_reason`

**Orchestrator-managed fields:** `status`, `current_iteration`, `files_changed`, `updated_at`

Nodes set `increments_iteration = True` (Planner does) so `Flow.run()` increments `current_iteration` immediately before each such node. `max_iterations` limits **planning rounds** only: after the Nth plan, Executor and Reviewer still run; the limit is enforced before starting another planning round (`current_iteration >= max_iterations` → `BLOCKED` without incrementing again). Resuming at Executor or Reviewer does not advance the counter until the next Planner visit.

## Change Detection

The `ChangeTracker` module (`core/changes.py`) detects files modified by the executor, so the reviewer can read them.

```
create_tracker(workspace)
  ├── git repo? → GitTracker (git status --porcelain, normalized to workspace-relative)
  └── no git?   → SnapshotTracker (os.walk before/after, mtime+size diff)
```

**Interface:**
- `tracker.snapshot()` — called in executor `prep()` before the agent runs
- `tracker.changes() → list[FileChange]` — called in executor `post()` after the agent runs

Both trackers return workspace-relative paths and filter `.rtw/` entries. The reviewer uses these paths to read file contents and include them in the review prompt.

## Gatekeeper

The gatekeeper is a deterministic validation layer that runs in each node's `post()` after the agent finishes. It enforces the document schema above and retries the agent with a focused correction prompt if required sections are missing.

### Validation

Per-stage checks:

| Stage    | Document    | Checks                                                       |
|----------|-------------|--------------------------------------------------------------|
| Planner  | PLAN.md     | Not empty, has `## Steps` with items, has `## Lessons`       |
| Planner  | SUBTASK.md  | Same checks when `plan_status` ≠ `COMPLETED` (omitted once the plan is completed) |
| Planner  | state.json  | `plan_status` is a valid value                               |
| Reviewer | SUBTASK.md  | Criteria are marked (✓/✗), exact heading `## Review`           |
| Reviewer | state.json  | `subtask_status` is a valid value                            |

Each check produces a `GateResult` with a list of issues (error/warning) and any repairs made.

### Retry on Failure

When validation finds errors (not warnings), `post()` calls the agent again with a minimal correction prompt:

```
The following issues were found in your output. Fix them.

- PLAN.md: '## Steps' section has no numbered items
- SUBTASK.md: Missing '## Acceptance criteria' section
- SUBTASK.md: '## Acceptance criteria' has no checklist items

Re-read the files listed above, add the missing sections, and ensure they are populated correctly.
```

The retry loop is bounded by a configurable limit (default: 2). If retries are exhausted and validation still fails, the issues are logged and the flow continues — fail-open, not fail-closed. The gatekeeper prevents silent structural drift without blocking progress.

### Two-Layer Design

1. **Prompt instruction (preventive)** — The planner and reviewer prompts explicitly state the required sections. The agent tries to get it right the first time.
2. **post() validation (corrective)** — Deterministic Python code catches what the agent missed and triggers a focused retry. Cannot be skipped.

## Prompts

Three prompt templates in `architect/prompts.py`. Each is a format string with placeholders filled from `prep()`.

### PLANNER

Role: Read TASK.md, maintain PLAN.md, write SUBTASK.md for the next step. Write SUMMARY.md when done.

Key instructions:
- PLAN.md must include numbered steps (✓ for completed) and a `## Lessons` section.
- SUBTASK.md must include clear instructions and an `## Acceptance criteria` checklist the Reviewer can verify by reading code.
- Update `state.json`: set `plan_status` and `blocking_reason`, preserve other keys.

### EXECUTOR

Role: Follow SUBTASK.md exactly. Create implementation files in the workspace, not under `.rtw/`.

The executor does not write plan documents or update `state.json`. It only modifies workspace files (source code, tests, configs).

### REVIEWER

Role: Check each acceptance criterion in SUBTASK.md against the changed file contents. Mark criteria ✓ or ✗ with a one-line reason. Update SUBTASK.md with a `## Review` section.

Update `state.json`: set `subtask_status` (`REVISE` | `PASSED` | `BLOCKED`) and `blocking_reason`.

## Flow Routing

```
Planner ──execute──► Executor ──review──► Reviewer
   ▲                    ▲                    │
   │                    │                    │
   └────── plan ────────┴──── execute ───────┘
        (PASSED)              (REVISE)
```

- **Planner → Executor**: `plan_status == IN_PROGRESS` → action `"execute"`
- **Executor → Reviewer**: agent success → `"review"`; on executor failure → `None` (`BLOCKED`, flow stops)
- **Reviewer → Planner**: `subtask_status == PASSED` → action `"plan"` (next step)
- **Reviewer → Executor**: `subtask_status == REVISE` → action `"execute"` (fix and retry)
- **Any → end**: `COMPLETED`, `BLOCKED`, or `None` action → flow stops

The `Flow` orchestrator manages the loop, enforces the planning-round limit via `Node.increments_iteration`, persists state after each node, and handles errors.

## Agent Backends

All backends implement `AgentBackend.execute(workspace, prompt, run_dir?) → AgentResult`.

`SubprocessAgentBackend` wraps CLI tools: builds command, runs subprocess, parses output. Subclasses override `_build_command()` and optionally `_parse_output()`.

| Backend              | CLI command       | Key flags                                     |
|----------------------|-------------------|-----------------------------------------------|
| `CursorAgentBackend` | `cursor-agent`    | `-p`, `--model`, `--workspace`, `--force`, `--trust` |
| `CodexAgentBackend`  | `codex`           | (stub)                                        |
| `ClaudeCodeBackend`  | `claude`          | (stub)                                        |

The backend is selected via `--backend` CLI flag. Environment variables: `RTW_RUN_DIR` and `RTW_STAGE` are set in the subprocess environment so hooks/tools can identify the active run context.

## Persistence and History

`StateStorage` manages the `.rtw/runs/<run_id>/` directory:

- `state.json` — written after every node completion
- `history/iter-NNN_PLAN.md` — snapshot when reviewer passes a subtask
- `history/iter-NNN_SUBTASK.md` — snapshot of the completed subtask (written before `SUBTASK.md` is removed)
- `history/iter-NNN_SUMMARY.md` — snapshot when plan completes

**Live `SUBTASK.md` removal:** On each `save()`, if `SUMMARY.md` exists in the run directory, `StateStorage` deletes the live `SUBTASK.md` file. The active subtask is no longer needed after completion; inspect the last subtask via `history/iter-NNN_SUBTASK.md` (captured when the reviewer last passed before completion).
- `traces/iter-NNN-{stage}-prompt.txt` / `-output.txt` — full agent prompts and outputs for debugging

Runs can be listed (`rtw list`) and resumed (`rtw resume`).

## CLI

```
rtw run <task.md>       # Start a new run
rtw list                # List all runs in workspace
rtw resume [run_id]     # Resume a run (latest if no ID given)
```

Flags: `--max-iter`, `--model`, `--backend`, `--workspace`, `--verbose`.

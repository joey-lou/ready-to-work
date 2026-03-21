# Known Issues

Issues identified by reviewing the codebase against `docs/ARCHITECTURE.md` and example runs. **Resolved** items are crossed off. **Open** items need attention.

## ~~Resolved~~

| # | Topic | Resolution | Verified |
|---|--------|------------|----------|
| ~~1~~ | ~~Gatekeeper retry used planner validator for reviewer~~ | `retry_with_corrections(..., validate=...)` — reviewer passes `validate_reviewer_output`. | Run `20260317_203419` ✓ |
| ~~2~~ | ~~Executor traced a rebuilt prompt~~ | `ExecutorNode.exec()` returns a dict including `prompt`; `post()` uses it for tracing. | Code ✓ |
| ~~3~~ | ~~Inconsistent `exec()` return types~~ | All three nodes return `dict[str, Any]` with `success`, `output`, `error`, `prompt`. | Code ✓ |
| ~~4~~ | ~~Iteration tied to planner `prep()`~~ | `Flow.run()` increments when `current_node.increments_iteration` (`PlannerNode` sets `True`). | Code ✓ |
| ~~5~~ | ~~`NOT_STARTED` rejected for `plan_status`~~ | Valid values derived from `PlanStatus` enum via `_plan_status_valid_values()`. | Code ✓ |
| ~~6~~ | ~~SUBTASK validation on completion iteration~~ | `validate_planner_output` skips SUBTASK.md checks when `plan_status` is `COMPLETED`. | Code ✓ |
| ~~7~~ | ~~SUBTASK deleted on completion undocumented~~ | Documented in `docs/ARCHITECTURE.md` (Persistence). | Docs ✓ |
| ~~8~~ | ~~Extra PLAN.md sections~~ | Prompt constrains to `## Steps` and `## Lessons` only. | Run `20260317_203419` ✓ |
| ~~9~~ | ~~`## Review section` vs `## Review`~~ | Gatekeeper regex `^##\s+Review\s*$`; prompt specifies exact heading. | Run `20260317_203419` ✓ |
| ~~10~~ | ~~`.rtw/` in `.gitignore`~~ | Present; `examples/**/.rtw/` negated. | `.gitignore` ✓ |
| ~~11~~ | ~~Flow used magic string `"Planner"` for iteration~~ | `Node.increments_iteration` (default `False`); `PlannerNode` sets `True`. | Code ✓ |
| ~~12~~ | ~~Duplicated `_read` / `_read_state`~~ | `core/io.py`: `read_text_if_exists`, `read_json_dict`. | Code ✓ |
| ~~13~~ | ~~Reviewer `_read_changed` instance method~~ | Module function `read_changed_workspace_files()` in `reviewer.py`. | Code ✓ |
| ~~14~~ | ~~Planner retry omitted `validate=`~~ | Explicit `validate=validate_planner_output`. | Code ✓ |
| ~~15~~ | ~~Executor returned `"review"` on failure~~ | On failure: `BLOCKED`, `return None`. | Code ✓ |
| ~~16~~ | ~~max_iterations blocked executor after Nth plan~~ | Limit enforced only before nodes with `increments_iteration`; executor runs after plan N when `max_iterations` is N. | `test_flow.py` ✓ |

## ~~Resolved (continued)~~

| # | Topic | Resolution | Verified |
|---|--------|------------|----------|
| ~~17~~ | ~~Prompts lacked format skeletons~~ | Planner and Reviewer prompts embed concrete PLAN.md/SUBTASK.md templates. Correction prompt includes relevant skeleton. | Run `20260318_215615` ✓ |
| ~~18~~ | ~~Reviewer gate didn't error on missing acceptance criteria~~ | `_validate_subtask_review` now checks `## Acceptance criteria` at error level. | Code ✓ |
| ~~19~~ | ~~Absolute paths in prompts~~ | Prompts use `{run_dir_rel}` / `{tmp_dir_rel}` (workspace-relative via `relpath_or_abs`). | Traces `20260318_215615` ✓ |
| ~~20~~ | ~~Inconsistent tmp-dir usage~~ | Planner prompt instructs verification steps to use `{tmp_dir_rel}` for scratch work. Run produced `verify_api.py`, `verification_report.json`, `verification.log` under tmp/. | Run `20260318_215615` ✓ |

## ~~Resolved (portability & prompts)~~

| # | Topic | Resolution | Verified |
|---|--------|------------|----------|
| ~~21~~ | ~~Reviewer appended full context to SUBTASK.md~~ | Reviewer prompt: edit only existing sections; no prompt dumps in SUBTASK. Gatekeeper errors on `# TASK.md` / `# PLAN.md` / etc. after `## Review`. | `test_gatekeeper.py` ✓ |
| ~~22~~ | ~~`state.json` absolute `run_dir` / `run_tmp_dir`~~ | `SharedState.to_dict()` persists them workspace-relative; `from_dict()` resolves (absolute legacy still loads). `workspace` stays absolute. | `test_state.py`, `test_storage.py` ✓ |
| ~~23~~ | ~~Verification scripts and `python -O`~~ | Planner prompt: prefer explicit pass/fail checks over bare `assert` alone. | Prompts ✓ |
| ~~24~~ | ~~PLAN.md embeds specific run ID~~ | Planner prompt: refer to tmp generically; no dated run folder names in steps. | Prompts ✓ |
| ~~25~~ | ~~Weak acceptance criteria wording~~ | Planner template + gatekeeper skeleton stress objectively checkable criteria (commands/expected output or exact symbols/values). | Prompts ✓ |

## Open

(none)
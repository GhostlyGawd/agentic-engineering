---
description: Single-tick orchestrator driver. Weeds stale nodes, computes the DAG ready set, dispatches a headless worker/reviewer pool into git worktrees, merges CLEAN branches in DAG order, calibrates role trust, then exits. One stateless tick per invocation; /loop or cron owns the cadence.
argument-hint: "[--once] [--pool N] [--weed-days N] [--integration-branch NAME]"
---

You are the loop engine for the orchestration tick. Tick CONTROL lives here;
tick STATE lives entirely in the MCP graph (`graph.db`). Drive it explicitly.

## Invocation

```
/agentic:orchestrate [--once] [--pool N] [--weed-days N] [--integration-branch NAME]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--once` | (on) | Run exactly one tick, then exit. Pass to `/loop` for cadence. |
| `--pool N` | 3 | Maximum headless worker processes to run in parallel per tick. |
| `--weed-days N` | 14 | Flag nodes untouched longer than N days as stale for triage. |
| `--integration-branch NAME` | (none) | If set, refuse to merge unless HEAD is this branch. On mismatch the tick skips ALL merges and escalates each CLEAN task; the claims stay held and those tasks remain in_progress until the deployment is corrected and the tasks are reset (no automatic self-healing). |

`--once` is the loop-friendly default: each `/loop` invocation fires one
`/agentic:orchestrate --once` in a fresh process. The orchestrator itself never
loops; `/loop` or cron owns the cadence.

## Single-tick contract

Each invocation is one stateless tick in a fresh process. It hydrates all state
from the graph at start, does one tick, and exits. No prior-tick context is
retained.

## The 7-step tick

### Step 1 - Weed

Call `flag_stale(days=<--weed-days>)` against all dispatched Specs. Surface the
stale set (nodes untouched > N days) to the user. Also surface any dispatched
Spec with no commit progress past the threshold.

Policy: surface only, never auto-close. The user decides on every stale node.

### Step 2 - Compute ready set

Compute the ready set by querying Task status plus the `implements` (Task->Spec)
and `depends-on` (Task->prerequisite) relations: a Task is ready when its parent
Spec is `dispatched` and every `depends-on` dependency is `resolved`. (This logic
is implemented and unit-tested in `scheduler.py` as the reference; the
orchestrator reproduces it via the graph query tools, with per-task graph
lookups.)

### Step 3 - Overlap filter

Partition the ready set into a runnable batch and a held set using
`detect_overlap(candidates=<list of {task_id, scope_paths} dicts>)`. Tasks that
share declared scope with an already-held Claim wait for a later serial tick
(serial-when-shared).

For each task in the runnable batch, call `claim_scope(task_id=<id>,
scope_paths=<paths>, worktree=<path>, branch=<name>)` to record the hold;
`claim_scope` returns a `claim_id` (a UUID, NOT the task id) - keep it for
`release_claim`. On a conflict return from `claim_scope` (rare race), drop that
task from the batch and continue.

### Step 4 - Dispatch pool

For each open slot (up to `--pool N`):
1. Create a git worktree + branch for the task.
2. Spawn a headless worker (`builder` agent) via the Pool execution engine.

Workers run as ephemeral `claude -p` subprocesses. The Pool enforces a
per-process timeout with process-tree kill on hang. Each worker result is a
structured `{task_id, ok, error}` dict - one failing job never aborts the
pool batch.

### Step 5 - Harvest, review, merge

Read each worker's structured result (task id, commit sha, exit status). Do not
retain worker transcripts.

**Worker clean** -> transition Task to `in_review`; spawn a headless reviewer
(full Phase-1 panel: spec-checker gate, then code-reviewer + contrarian
blind-parallel, managing the critical loop with 3-iteration diagnostic).

**Reviewer CLEAN** -> merge CLEAN branches in dependency order (topological by
`depends-on`); the `merge_order` reference implementation lives in `scheduler.py`.
Merge each CLEAN branch into the integration branch in that order; call
`release_claim(claim_id=<id>)` (the UUID from `claim_scope`, not the task id)
after each merge.

**Conflict or escalation** -> surface to the user (branch name + finding
summary). Leave the branch unmerged, the Claim held. Do NOT auto-resolve.

**Retry cap** -> NEEDS_FIXING verdicts and launch/setup failures route through a
per-task CriticalLoop; a task that fails 3 times escalates (status `escalated`)
instead of re-dispatching forever. An escalating launch/setup failure is
recorded in both `failed` and `escalations`.

### Step 6 - Calibrate

For each role that acted this tick, call `record_outcome(role=<name>, hit=<bool>)`:
- Hit: a raised Critical was resolved via root-cause fix, or a logged Strength
  validated.
- Miss: stability contradiction (approved a file a later Critical hit), or a
  missed Critical.

Then call `get_calibration(role=<name>)`. If a threshold is crossed, call
`adjust_trust(role=<name>)`.

Scheduling honors a `distrusted` role by requiring a second reviewer on its
tasks and discounting its Criticals (will not merge-block on them alone until
re-validated after recovery).

### Step 7 - Exit

Write the tick summary: tasks dispatched, workers clean/failed, merges completed,
claims released, stale nodes surfaced, calibration adjustments fired. Exit the
process.

Summary keys of note:

- `stale_nodes` -> read-only ids of stale non-terminal nodes surfaced for triage
  (never auto-closed). NOTE: a stale dispatched Spec can appear in BOTH `weeded`
  and `stale_nodes` - they are different signals (flagged-for-escalation vs
  surfaced-for-triage), so do not assume the two lists are disjoint.

## Defaults and policies

| Setting | Default | Policy |
|---------|---------|--------|
| Pool size | 3 | `--pool N` to override |
| Weed threshold | 14 days | `--weed-days N` to override |
| Merge policy | auto-merge on reviewer-CLEAN | full autonomy |
| Conflicts / escalations | always surfaced, never auto-resolved | human decision point |
| Tick termination | always exit after one tick | the tick never loops; `/loop`/cron decides whether to fire the next one |

The tick always exits after one beat. `/loop` (or cron) owns the cadence: it
keeps firing ticks (no hard global stop condition) while ready tasks or open
CriticalLoops remain, and idles once both queues are empty. Each tick summary
reports whether work or open loops remain so the cadence layer can decide.

## ASCII note

All command-string examples in this doc use ASCII only (no em-dash, smart quotes,
or right-arrow characters) - required for PowerShell 5.1 compatibility.

# Phase 2 Design - Orchestration & Parallelism

**Date:** 2026-05-23
**Status:** Implemented (Phase 2)
**Phase:** 2 of the Agentic Engineering System (see `agentic-engineering-system-prd-v3.md`)
**Branch context:** built on `phase-2-retro-integration-layer` (PR #2 adds the `integration` failed_layer + versioned-migration framework this design extends).

## Goal

Multiple builder teams in flight at once, coordinated by an orchestrator, without merge collisions - plus scheduled graph weeding, stale-spec detection, and per-role confidence calibration.

**PRD exit gate:** two teams run in parallel on orthogonal tasks without merge collisions; graph weeding runs on schedule; at least one confidence-calibration adjustment has fired.

## Locked decisions (from brainstorming)

| Decision | Value |
|----------|-------|
| Scope | All six Phase 2 build items in one design + one implementation plan. |
| Concurrency model | Graph-backed loop board: the graph IS the board; workers/reviewers atomic-claim graph-ready tasks; worktrees isolate the filesystem. |
| Execution model | Headless pool: orchestrator spawns ephemeral `claude -p ... --permission-mode bypassPermissions` worker/reviewer processes, one per orthogonal claimed task, each in its own worktree. Pool size caps parallelism. |
| Orchestrator lifespan | **Single-tick and stateless.** One tick per process; hydrates entirely from `graph.db`, does one tick, exits. `/loop` (or cron) owns the cadence. No long-lived session - nothing accumulates a transcript. |
| Calibration semantics | Trust-weighting that gates behavior: a threshold-crossing changes scheduling (down-weight an unstable reviewer / require a second opinion; fast-path a consistently-accurate one). |
| Execution engine | Promote `tests/llm_harness.py` to `src/agentic_mcp/headless.py` (subprocess + timeout + process-tree-kill already solved); add a pool wrapper. |

## 1. Runtime topology

```
                 +-------------------------------------------+
                 |  /agentic:orchestrate --once  (one tick)   |
                 |  fresh process each beat; /loop = cadence   |
                 +---------------+-----------------------------+
                                 | hydrates from / writes to
                          +------v--------+
                          |  graph.db      |  <- the board (Specs, Tasks,
                          |  (SQLite)      |     CriticalLoops, Claims, Calib)
                          +------+--------+
        spawns headless          | harvests structured results
   claude -p processes (pool)    | (task id, sha, pass/fail) - NOT transcripts
        +------------+-----------+-----------+
        v            v                       v
   [worker A]   [worker B]   ...         [reviewer]
   worktree-A   worktree-B               worktree-A
   one task     one task                 drives Phase-1 critical loop
```

**Context safety is the central invariant.** Every process in the system is context-bounded:

| Process | Lifespan | Context risk |
|---------|----------|--------------|
| Orchestrator tick | one tick | none - fresh, graph-hydrated each beat |
| Worker | one task | none - ephemeral |
| Reviewer | one review | none - ephemeral |
| `graph.db` | persistent | N/A - a database, not a context |

The graph is the only memory. The orchestrator never retains worker transcripts - it reads back only structured results (task id, commit sha, exit status). This is the same single-tick discipline the existing `pm` skill follows ("each /loop invocation runs exactly one PM tick").

## 2. Execution engine

Move `mcp-server/tests/llm_harness.py` -> `mcp-server/src/agentic_mcp/headless.py`. It already provides subprocess launch, `--output-format json` `result`-field parse, timeout, UTF-8 decode, and **process-tree kill on hang** - exactly the primitives a pool needs. The 4 `llm`-marked e2e tests update their import to the new home.

Add a `Pool` wrapper:
- Launch up to N headless processes (default N=3), each handed one task + one worktree path.
- Harvest results as processes finish; backfill the next ready, non-overlapping task.
- Capture per-process structured result (task id, commit sha, exit status, stderr tail on failure) and return it for write-back to the graph.
- Enforce a per-process timeout with the existing process-tree kill.

## 3. The orchestrator tick (`/agentic:orchestrate --once`)

A tick is **stateless** - all inputs come from the graph, all outputs go back to the graph or to commits. Worker results are read back from the graph, never retained in orchestrator context.

1. **Weed** - surface graph nodes untouched > N days (default 14) for triage via `flag_stale`; flag dispatched Specs with no commit progress as stale. Surface only - never auto-close. Escalations go to the user.
2. **Compute ready set** - Tasks whose `blockedBy` deps are all resolved and whose parent Spec is dispatched.
3. **Overlap filter (serial-when-shared)** - each ready Task carries a Claim (modules/files it will touch, derived from its Spec's declared scope). `detect_overlap` returns the maximum non-overlapping batch; overlapping Tasks are held for a later serial tick.
4. **Dispatch** - for each open pool slot: create a worktree + branch, write a held Claim, spawn a headless worker.
5. **Harvest** - as workers finish:
   - worker-clean -> transition Task to `in_review`, spawn a headless reviewer (full Phase-1 panel: spec-checker gate, then code-reviewer + contrarian blind-parallel; manages the critical loop, fires the 3-iteration diagnostic).
   - reviewer CLEAN -> merge the worktree branch into the integration branch **in DAG order**; release the Claim.
   - conflict or escalation -> surface to user; leave the branch unmerged and the Claim held.
6. **Calibrate** - update each acting role's track record from this round's outcomes; if a threshold is crossed, `adjust_trust` fires (section 6).
7. **Terminate the tick** - exit the process. The board state fully reflects progress. `/loop`/cron decides whether to fire another tick; it idles (no hard global stop) while ready Tasks or open CriticalLoops remain.

## 4. Graph additions (schema `user_version` -> 3)

Extends the versioned-migration framework landed in PR #2. Note: migration constants are named by **schema version, not project phase** - the integration-layer change (PR #2) already claimed `user_version = 2`, so this Phase 2 orchestration migration is the third schema version. Add `_migrate_to_v3` alongside the existing `_migrate_to_phase_1` / `_migrate_to_phase_2`, and bump `SCHEMA_VERSION = 3`. (Renaming the older phase-named constants to version-named ones is an optional tidy-up the plan may include; not required.) All migrations idempotent.

- **`claim`** table - `id, task_id, scope_paths (JSON array), worktree, branch, status (held|released), created_at`. Backs serial-when-shared and worktree bookkeeping.
- **`calibration`** table - `role TEXT PRIMARY KEY, observations INTEGER, hits INTEGER, misses INTEGER, score REAL, last_adjusted_at TEXT, distrusted INTEGER (0|1)`. One row per role.
- **`spec.stale_flagged_at`** column (TEXT, nullable) - weeding output.
- Worktree/lease columns on `task` as needed for harvest bookkeeping.

## 5. New MCP tools (Phase 2)

| Tool | Purpose |
|------|---------|
| `claim_scope` | Record a Task's claimed paths; returns a conflict result if they overlap an open held Claim. |
| `release_claim` | Release a Claim on task completion/merge. |
| `detect_overlap` | Given a ready set, return the maximum non-overlapping batch (the scheduler's core query). |
| `flag_stale` | Mark Specs/nodes stale-for-triage (weeding output). |
| `record_outcome` | Append a hit/miss to a role's calibration record. |
| `get_calibration` | Read a role's current score + distrust flag (orchestrator consults before scheduling reviews). |
| `adjust_trust` | On threshold-crossing: set/clear `distrusted`, stamp `last_adjusted_at`. **This firing satisfies the exit gate.** |

Phase 2 total tool surface: 18 (Phase 0+1) + 7 = **25**.

## 6. Confidence calibration (trust-weighting)

Each role accrues observations recorded via `record_outcome`:

- **Reviewer hit** - a Critical it raised was confirmed (resolved via a real root-cause fix), or a logged Strength later validated.
- **Reviewer miss** - a Phase-1 **stability contradiction** (it approved a byte-identical file that a later Critical hit), or a Critical it should have caught surfaced the next round.

Score = smoothed hit-rate (exact smoothing constant fixed in the plan; a simple Laplace-smoothed ratio is the default).

**Adjustment behavior on threshold-crossing (`adjust_trust`):**
- Score below floor -> `distrusted = true`: the orchestrator **requires a second reviewer** on that role's PRs and **discounts its Criticals** (will not merge-block on them alone until re-validated).
- Sustained recovery above ceiling -> clear `distrusted`; optionally fast-path (single reviewer).

The exit gate ("at least one calibration adjustment has fired") is satisfied when `adjust_trust` flips a flag and the next tick's scheduling honors it. The e2e test forces this deterministically with a scripted reviewer miss.

## 7. Surface: commands / agents / skills

- **`/agentic:orchestrate`** (new command) - the tick driver. Args: `--once` (single tick; the loop-friendly default invocation), `--pool N` (default 3), `--weed-days N` (default 14).
- **`agents/orchestrator.md`** (new agent) - system prompt for the scheduler role. Implements nothing: computes the DAG, detects overlap, weeds, calibrates, surfaces escalations. Concise, no cross-plugin references.
- Workers/reviewers reuse the Phase-1 agents (`builder.md`, `code-reviewer.md`, `contrarian.md`, `spec-checker.md`) - now invoked headlessly instead of in-session.
- `skills/router/SKILL.md` updated to document the 7 new tools.
- README updated: Phase 2 surface, tool count 18 -> 25, exit-gate description.

## 8. Testing

**Fast suite (no live CLI):**
- `detect_overlap` - orthogonal vs. shared scope sets return correct batches.
- DAG ordering - merge order respects `blockedBy`.
- Weeding threshold - nodes past N days flagged, fresh nodes untouched.
- Calibration - scoring math; `adjust_trust` threshold-crossing sets/clears `distrusted` exactly at the boundary.
- Claim lifecycle - `claim_scope` conflict detection, `release_claim`.
- Migration v2 -> v3 idempotency (re-run is a no-op).
- `Pool` wrapper logic with a stubbed launcher (no real `claude` process) - launch/harvest/backfill/timeout.

**`llm` e2e (the exit gate, behind the `llm` marker):**
- Two orthogonal Specs build in parallel in separate worktrees and merge to the integration branch without collision.
- Weeding surfaces a deliberately-stale node on a tick.
- A scripted reviewer miss drives `adjust_trust` to fire, and the next tick honors the distrust flag (second reviewer required).
- Deterministic via staged graph fixtures + `--mcp-config` (same staging the Phase 1 e2e uses).

## 9. Defaults (configurable)

| Setting | Default | Notes |
|---------|---------|-------|
| Pool size | 3 | `--pool N`. |
| Weed threshold | 14 days | `--weed-days N`. |
| Merge policy | auto-merge on reviewer-CLEAN | full autonomy; matches the headless model. |
| Conflicts / escalations | always surfaced, never auto-resolved | human decision point. |
| Tick termination | exit after one tick | `/loop`/cron owns cadence; idles while work or open loops remain. |

## 10. Out of scope (deferred)

- `sqlite-vec` / vec0 (Phase 3).
- pattern-finder, periodic architectural review, cross-project meta-graph (Phase 3).
- self-improvement / reviewer-calibration *learning* beyond the trust-weighting gate (Phase 4).
- A portable POSIX hook (the system remains Windows-first; headless `claude -p` invocation is shell-agnostic, but the orchestrator's worktree/loop scaffolding targets PowerShell first).

# Handoff - Agentic Engineering System, Phase 2.1 complete; next = headless build+review loop

> Paste-ready context for a fresh Claude Code session opened with `cwd = D:\GitHub Projects\Studies\Superpowers Study`. (Supersedes the Phase 2 handoff.)

## What this project is

A self-improving engineering system packaged as a Claude Code plugin, dogfooded into its own repo. Upstream: `github.com/GhostlyGawd/agentic-engineering`. A typed SQLite knowledge graph (`./.agentic/graph.db`) backs everything; durable writes go through the bundled stdio MCP server (`agentic-graph`).

## Current state (as of 2026-05-23)

- **Branch:** `main`. Phase 2 (PR #2) and **Phase 2.1** are both merged locally. Merge commit for 2.1 is `b3ec4b6` ("Merge Phase 2.1: orchestration hardening + headless loop design").
- **`main` is AHEAD of `origin/main`** by the Phase 2.1 commits - it was a LOCAL merge, not yet pushed. Decide whether to `git push origin main` (no PR was used for 2.1).
- **Tests:** `160 passed, 7 deselected` (fast suite). Run FROM `mcp-server/`: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`.
- Phases 0, 1, 1.5, 2, 2.1 are done. Phase 3 (pattern-finder, periodic architectural review, `sqlite-vec`/vec0) is not started.

## YOUR NEXT TASK: write the implementation plan for the headless build+review loop

The spec is written and APPROVED (brainstorming done). It is NOT yet planned or implemented.

- **Spec:** `docs/superpowers/specs/2026-05-23-headless-build-review-loop-design.md` - READ THIS FIRST.
- **Next step:** invoke `superpowers-extended-cc:writing-plans` against that spec to produce `docs/plans/2026-05-23-headless-build-review-loop.md` (+ `.tasks.json`), then execute via `superpowers-extended-cc:subagent-driven-development`.
- Do NOT re-brainstorm; the design decisions below are locked. Do NOT relitigate scope.

### Why this work exists (the gap it closes)

The orchestrator's headless `tick()` does NOT actually build or review yet:
- `_real_launch` (orchestrate.py) sends every worker a GENERIC prompt ("implement the assigned task") with no task content and no graph read - workers build nothing meaningful.
- `_real_review` is a STUB that returns `{"verdict": "CLEAN"}` unconditionally - nothing reviews the code before merge.

The Phase 2 e2e proved the MECHANISM (parallel `claude -p` workers in worktrees + claims + merge) but it overrode both seams with a hand-written prompt + stubbed review. This task makes the two seams real. It is the missing rung between Phase 2 (orchestration mechanism) and Phase 3 (meta-review), which the PRD assumed but never gated.

### Locked design decisions (from the approved spec)

1. **Close the whole loop** - make BOTH `_real_launch` (real build) and `_real_review` (real review) real. You cannot meaningfully review code a generic prompt never built.
2. **Reviewer = headless `/agentic:review-pr`, verdict from the graph.** `_real_review` spawns `claude -p "/agentic:review-pr <spec_id>"` in the worktree; that command IS the full four-role loop engine (spec-checker gate -> code-reviewer + contrarian -> builder loop-fix -> re-loop until clean/diminishing-returns). Then derive the verdict from the graph: any open Critical scoped to the spec -> NEEDS_FIXING, else CLEAN. Do NOT parse stdout.
3. **Builder = graph-assembled task prompt.** A new pure helper `_build_builder_prompt(conn, task_id)` reads the Task body + parent Spec criteria (via the `implements` relation) and returns a builder-role prompt; `_real_launch` runs `claude -p <that prompt>`.
4. **Thread-safety:** `headless.Pool` runs `launch_fn` in THREADS and sqlite3 connections are not thread-safe. So assemble prompts (and stage the mcp_config) in `tick()` (single-threaded, owns `conn`) BEFORE dispatch, and pass them into the job dict. `_real_review` runs in tick()'s single-threaded review phase, so it CAN use `conn`.
5. **Error/timeout safety:** `_real_review` catches its own exceptions and returns NEEDS_FIXING (never merge unreviewed code); the Phase 2.1 retry cap then terminates a persistently unreviewable task after 3 strikes. Preserves tick()'s never-raise contract.
6. **Assumptions (explicit):** one-task-per-spec as the reviewable unit (matches the existing e2e); LIVE-ONLY execution (fast suite keeps stubbing all seams; new behavior verified by an `llm`-marked e2e); workers run `--permission-mode bypassPermissions`; calibration `calibrate=False` for now (no ground truth at review time).
7. **Two pure helpers are fast-unit-testable** (no `claude`): `_build_builder_prompt` (prompt contains task body + criteria) and `_verdict_from_graph(conn, spec_id)` (open Critical -> NEEDS_FIXING). Only the actual `claude -p` calls are live-only.

### Headless plumbing you will use (already exists in `headless.py`)

- `run_claude_headless(prompt, cwd, timeout=900, mcp_config=None) -> dict` - runs `claude -p ... --output-format json --permission-mode bypassPermissions`; kills the process tree on timeout.
- `result_text(payload) -> str` - assistant's final text from the JSON payload.
- `stage_mcp_config(project, db_path) -> Path` - writes a RESOLVED `.mcp.json` registering `agentic-graph` using `sys.executable`. THIS WORKS - the old "MCP never connected" memory was a different, bare-command config. Use this to give workers/reviewers graph access.
- `Pool(max_workers).run(jobs, launch_fn)` - thread pool; `launch_fn` MUST catch its own exceptions and return a structured result (it must never raise into the Pool).
- `tick()` will need the DB path to stage the mcp_config - thread it in (the CLI `main()` already has it via `db.resolve_db_path()`).

### Reusable assets

- Agents: `agents/builder.md`, `agents/code-reviewer.md`, `agents/contrarian.md`, `agents/spec-checker.md`.
- Commands: `commands/dispatch.md` (spec-centric: validates + locks spec, kicks builder iter 1 - granularity mismatch with per-task worktrees, so prefer the graph-assembled prompt), `commands/review-pr.md` (the loop engine you run headless).
- e2e patterns: `mcp-server/tests/test_phase2_e2e.py` - `_make_launch_fn` (concrete per-task prompt), `stage_mcp_config`, `_setup_git_repo`. Extend these for the new live e2e.

## Phase 2.1 - what just landed (context; do not redo)

All merged in `b3ec4b6`. Spec: `docs/superpowers/specs/2026-05-23-phase-2.1-followups-design.md`. Plan: `docs/plans/2026-05-23-phase-2.1-orchestration-hardening.md`.

1. **Retry cap** - `NEEDS_FIXING` + launch/setup failures route through a per-task CriticalLoop (`_handle_failure`, linked via a `dispatch-failure` Finding with `parent_id==task_id`): reset to pending on strikes 1-2, escalate (status `escalated`) on the 3rd. The dispatch loop is resolved when a task is confirmed CLEAN (not just on merge), so the strike budget stays correct if the merge is skipped/fails.
2. **Node-level weeding** - `tick()` surfaces `result["stale_nodes"]` (read-only ids). A stale Spec can appear in both `weeded` and `stale_nodes` (different signals).
3. **`_db_path` dedup** - now `db.resolve_db_path()`; both CLIs use it.
4. **Opt-in integration-branch enforcement** - `tick(integration_branch=...)` / CLI `--integration-branch NAME`: on HEAD mismatch, skip ALL merges + escalate each CLEAN task (claims held, tasks stay `in_progress`; needs an external reset - no self-healing).

**Deferred follow-up (capstone #2, documented not implemented):** `result["escalations"]` holds two dict shapes - retry-cap `{task_id, reason, iterations}` (terminal, claim released) vs branch/merge `{task_id, error}` (held, recoverable). Consider a `kind`/`terminal` discriminator field.

## Execution model (locked - do not relitigate)

The graph IS the board. The orchestrator is STATELESS SINGLE-TICK (`/agentic:orchestrate --once`; `/loop` or cron owns the cadence) - each tick a fresh, graph-hydrated process. Ephemeral headless `claude -p ... --permission-mode bypassPermissions` workers/reviewers, one per orthogonal claimed task, isolated in git worktrees. Serial-when-shared via scope claims; DAG-ordered merge; trust-weighting calibration gates scheduling.

## Repo conventions & gotchas

- Windows + PowerShell 5.1. Venv python: `mcp-server/.venv/Scripts/python.exe`. RUN PYTEST FROM `mcp-server/`. Fast suite: `pytest -m "not llm"`. Live gate: `pytest -m llm` (needs the `claude` CLI on PATH).
- Module style: `conn` first arg, `conn.commit()` after writes (reads need none), `_now()` = `datetime.now(timezone.utc).isoformat(timespec="seconds")`.
- Relations table is `relations`; valid types include `implements` (Task->Spec) and `depends-on` (Task->prereq) - there is NO `belongs-to`/`blocked-by`. Use `relations.neighbors(conn, id, type, direction)`.
- `finding` has `subtype` + `parent_id` (indexed); `critical_loop` has `finding_id`, `iteration_count` (DEFAULT 1), `diagnostic_fired_at`; `loops.DIAGNOSTIC_THRESHOLD == 3`. Statuses are free-text (no CHECK), so `escalated` is valid.
- Migration constants named by SCHEMA VERSION (`_migrate_to_vN`, `SCHEMA_VERSION = 3`), not project phase.
- ASCII-only inside `.ps1` / command-doc string literals (PS 5.1 cp1252 decoding). Avoid `2>&1` on native exes in PS 5.1 (stderr arrives wrapped as `RemoteException`, cosmetic).
- **Skill policy** (`CLAUDE.md`): only auto-invoke `superpowers-extended-cc` plugin skills in this repo. **Ignore `norns-loop-review/` entirely.**
- **Model preference (user):** dispatch subagent-driven-development implementers AND reviewers with `model: opus`, not cheaper models - quality over cost, even for "mechanical" tasks.

## How Phase 2 / 2.1 were built (process reference)

brainstorming -> writing-plans -> subagent-driven-development: a fresh implementer subagent per task (opus), two-stage review (spec compliance, then code quality) after each, then a final whole-implementation capstone review. The Phase 2.1 capstone caught a real strike-budget off-by-one at the retry-cap/branch-guard seam (fixed + test-covered before merge). Same pattern works for the headless loop and Phase 3. Verify reports by reading the diff - one implementer confabulated "already present" narration while actually doing the work correctly.

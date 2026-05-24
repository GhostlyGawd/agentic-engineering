# Handoff - Agentic Engineering System, Phase 2 complete

> Paste-ready context for a fresh Claude Code session opened with `cwd = D:\GitHub Projects\Studies\Superpowers Study`. (Supersedes the prior Phase 0 handoff.)

## What this project is

A self-improving engineering system packaged as a Claude Code plugin, dogfooded into its own repo. Upstream: `github.com/GhostlyGawd/agentic-engineering`. A typed SQLite knowledge graph (`./.agentic/graph.db`) backs everything; durable writes go through the bundled stdio MCP server (`agentic-graph`).

## Current state (as of 2026-05-23)

- **Branch:** `phase-2-retro-integration-layer`, base `main`. Pushed.
- **PR #2 - "Phase 2: Orchestration & Parallelism"** - OPEN, 26 commits: https://github.com/GhostlyGawd/agentic-engineering/pull/2. User accepted it; check `gh pr view 2 --json state` to see whether it has been merged on GitHub yet.
- Phases 0, 1, 1.5 are already merged to `main`. Phase 2 is this PR.
- **Tests:** `147 passed, 7 deselected` (fast suite). **Live exit-gate e2e: 3/3 at HEAD.**

## What Phase 2 added

- **Schema v3** (`migrations.py` / `schema.sql`): `claim` + `calibration` tables, `spec.stale_flagged_at`. Idempotent; fresh-init and v2->v3 upgrade both verified.
- **Modules:** `claims.py` (scope claims + `detect_overlap`), `weeding.py` (`flag_stale_specs`; `find_stale_nodes` exists but is UNWIRED), `calibration.py` (trust-weighting), `scheduler.py` (`ready_tasks` + `merge_order`), `orchestrate.py` (the stateless `tick()` + `python -m agentic_mcp.orchestrate --once` CLI), `headless.py` (promoted from `tests/llm_harness.py` + `Pool`).
- **7 new MCP tools** (25 total): `claim_scope, release_claim, detect_overlap, flag_stale, record_outcome, get_calibration, adjust_trust`.
- **`agents/orchestrator.md`, `commands/orchestrate.md`, `tests/test_phase2_e2e.py`** (llm-marked exit gate).
- **Design:** `docs/superpowers/specs/2026-05-23-phase-2-orchestration-design.md`. **Plan:** `docs/plans/2026-05-23-phase-2-orchestration.md` (+ `.tasks.json`, all 10 tasks completed).

## Execution model (locked - do not relitigate)

The graph IS the board. The orchestrator is STATELESS SINGLE-TICK (`/agentic:orchestrate --once`; `/loop` or cron owns the cadence) - each tick a fresh, graph-hydrated process, so nothing accumulates a transcript. Ephemeral headless `claude -p ... --permission-mode bypassPermissions` workers/reviewers, one per orthogonal claimed task, isolated in git worktrees. Serial-when-shared via scope claims; DAG-ordered merge; trust-weighting calibration gates scheduling.

## Open Phase 2.1 follow-ups

Items 1-4 are now CLOSED (landed in Phase 2.1). Only item 5 remains open.

### Closed in Phase 2.1

1. **Retry cap** - DONE. `NEEDS_FIXING` verdicts and launch/setup failures route through a per-task CriticalLoop: reset to pending on strikes 1-2, escalate (status `escalated`) on the 3rd. Escalating launch/setup failures appear in both `result["failed"]` and `result["escalations"]`.
2. **Node-level weeding** - DONE. `tick()` now surfaces `result["stale_nodes"]` (read-only ids of stale non-terminal nodes) alongside `result["weeded"]`. NOTE: weeding remains scoped to dispatched Specs; `stale_nodes` is the surfaced-for-triage signal (a stale Spec can appear in both lists).
3. **`_db_path` duplicated** - DONE. Extracted to `db.resolve_db_path()`; the duplicate `_db_path` removed from `server.py` and `orchestrate.py`.
4. **Integration branch** - DONE. Enforcement is now opt-in via `tick(integration_branch=...)` / CLI `--integration-branch NAME`: on HEAD mismatch the tick skips ALL merges and escalates each CLEAN task (claims stay held, tasks remain `in_progress`). Default (None) preserves the documented-only assumption.

### Open (none blocking)

5. **Python `tick()` `review_fn` is a CLEAN stub** - the full Phase-1 review panel is the orchestrator AGENT's job (driven via tool calls); the seam exists for injection (the e2e overrides it). A real headless build+review loop is now designed in `docs/superpowers/specs/2026-05-23-headless-build-review-loop-design.md`.

## Repo conventions & gotchas

- Windows + PowerShell 5.1. Venv python: `mcp-server/.venv/Scripts/python.exe`. RUN PYTEST FROM `mcp-server/`. Fast suite: `pytest -m "not llm"`. Live gate: `pytest -m llm` (needs the `claude` CLI on PATH).
- Module style: `conn` first arg, `conn.commit()` after writes, `_now()` = `datetime.now(timezone.utc).isoformat(timespec="seconds")`.
- Relations table is `relations`; valid types include `implements` (Task->Spec) and `depends-on` (Task->prereq) - there is NO `belongs-to`/`blocked-by`. Use `relations.neighbors(conn, id, type, direction)`.
- Migration constants are named by SCHEMA VERSION (`_migrate_to_vN`, `SCHEMA_VERSION = 3`), not project phase (phase/version diverged when the integration-layer change took v2).
- ASCII-only inside `.ps1` / command-doc string literals (PS 5.1 cp1252 decoding).
- Avoid `2>&1` on native exes in PS 5.1; native-exe stderr arrives wrapped as `RemoteException` (cosmetic).
- **Skill policy** (`CLAUDE.md`): only auto-invoke `superpowers-extended-cc` plugin skills in this repo. **Ignore `norns-loop-review/` entirely.**

## Likely next actions

- If PR #2 is merged: sync `main`, delete the `phase-2-retro-integration-layer` branch.
- Or start the Phase 2.1 follow-up cycle, or Phase 3 (pattern-finder, periodic architectural review, `sqlite-vec`/vec0) per `agentic-engineering-system-prd-v3.md`.

## How Phase 2 was built (process reference)

brainstorming -> writing-plans -> subagent-driven-development: a fresh implementer subagent per task, two-stage review (spec compliance, then code quality) after each, then a final whole-implementation capstone review (which caught a Critical the per-task tests missed: a worktree re-dispatch crash, now fixed + test-covered). Same pattern works for Phase 2.1 / Phase 3.

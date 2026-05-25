# Handoff - Phase 3 sub-project A (pattern-finder) complete; next = sub-project B (architectural review)

> Paste-ready context for a fresh Claude Code session opened with `cwd = D:\GitHub Projects\Studies\Superpowers Study`. Supersedes the headless-build-review-loop handoff (that work is merged).

## What this project is

A self-improving engineering system packaged as a Claude Code plugin, dogfooded into its own repo. Upstream: `github.com/GhostlyGawd/agentic-engineering`. A typed SQLite knowledge graph (`./.agentic/graph.db`) backs everything; durable writes go through the bundled stdio MCP server (`agentic-graph`). PRD: `agentic-engineering-system-prd-v3.md`. Phase 3 (Meta-Review) is decomposed in `docs/plans/2026-05-24-phase-3-decomposition.md`.

## Current state (as of 2026-05-24)

- **Branch:** `main`, synced with `origin/main` at `97f3c87`. Phases 0, 1, 1.5, 2, 2.1, the headless build+review loop, and **Phase 3 sub-project A (pattern-finder)** are all merged.
- **Phase 3 sub-project A merged via PR #3** (`fb63a60`). It delivers the `Pattern` half of the Phase 3 PRD exit gate ("one real Pattern produced and triaged"), live-validated.
- **Tests:** `199 passed, 9 deselected` (fast suite). Run FROM `mcp-server/`: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`. Live gate: `-m llm` (needs `claude` on PATH).
- Phase 3 remaining: **sub-project B (architectural review)** = YOUR NEXT TASK, then sub-project C (cross-project meta-graph, deferrable - inert under default `isolated` scope).

### Update 2026-05-25: always-on companion rung 0+1 landed (branch `feat/always-on-companion-vision`)

- **Rung 0 (busy_timeout):** `db.connect` now sets `PRAGMA busy_timeout = 5000` explicitly (resolves the tracked follow-up below). Note: Python 3.12's `sqlite3.connect` already defaults `timeout=5.0`, so the value was effectively 5000 already; the explicit PRAGMA makes the intent durable.
- **Rung 1 (supervisor daemon):** a logic-free scheduler that fires the EXISTING `orchestrate`/`pattern_finder` `--once` CLIs on per-project cadences from `~/.agentic/registry.json`, with ephemeral state in `~/.agentic/supervisor.db` and a `127.0.0.1` health/control API. New console script: **`agentic-supervisor`** (`--once` runs a single pass and prints JSON; no args = run-forever loop + control API on port 8787). New modules under `mcp-server/src/agentic_mcp/`: `supervisor_config.py`, `supervisor_state.py`, `tick_spawn.py`, `supervisor.py`, `control_api.py`. Windows keep-alive: `mcp-server/scripts/install-supervisor.ps1` (`-Print` dry-run). Example registry: `mcp-server/examples/registry.example.json`.
- The supervisor adds NOTHING to tick logic - it shells out to the existing CLIs (`python -m agentic_mcp.orchestrate --once --repo <path>` with `AGENTIC_DB_PATH` set). Smoke-tested end to end against this repo: both ticks fired, zero errors.
- **Tests:** `245 passed, 9 deselected` (199 prior + 46 new). Plan: `docs/superpowers/plans/2026-05-25-rung0-1-supervisor.md`.
- **Remaining rungs 2-4** (HUD, approval gate, auto-rehydration) are unbuilt - see the vision doc `docs/superpowers/specs/2026-05-25-always-on-companion-vision-design.md`. Approve/decline/retry endpoints and `arch_review`/`promotion` tick CLIs are intentionally deferred to those rungs.

## YOUR NEXT TASK: brainstorm + build sub-project B (architectural review)

Sub-project B is **NOT yet brainstormed**. Start with `superpowers-extended-cc:brainstorming` (there are real design forks below - do not skip to a plan). Then design spec -> `superpowers-extended-cc:writing-plans` -> `superpowers-extended-cc:subagent-driven-development` (see "Execution model" below for the dogfooding caveat).

### What B is (PRD Phase 3, top-down half)

The architectural-review layer hunts systemic/shape problems on a cadence, with an incentive isolated from shipping any single PR. PRD deliverables for B:
- Architectural-review agent with cadence + incentive isolation.
- Periodic alignment check against the original `Goal`.
- Architectural-map tripwire.
- Produces `ArchDebt` nodes (triaged).

**Exit gate B closes:** the `ArchDebt` half of the Phase 3 PRD exit gate ("one real ArchDebt produced and triaged"). A + B together satisfy the full Phase 3 exit gate except the conditional meta-graph clause (sub-project C).

### Reusable template: sub-project A is your blueprint

A (pattern-finder, `mcp-server/src/agentic_mcp/patterns.py`) and the headless loop (`orchestrate.py`) already established the exact shape B should mirror:
- **Pure deterministic core** + **injectable seam** (the only thing that touches `claude`, stubbed in the fast suite) + **never-raise single-tick driver** + **CLI** + **agent .md** + **command .md** + **`llm`-marked e2e**.
- **Headless agent machinery (reuse, do not reimplement):** `headless.run_claude_headless(prompt, cwd, timeout=900, mcp_config=None)` (prompt via stdin; `bypassPermissions`), `headless.stage_mcp_config(project, db_path)`, `headless.claude_on_path()`. The staged-agents pattern: copy an agent `.md` into `<repo>/.claude/agents/` then run headless so the agent self-mints nodes via MCP - see `orchestrate._stage_review_agents`/`_real_review` and `patterns._stage_pattern_agent`/`_real_confirm`.
- **Derive outcomes from the graph, never parse prose** (load-bearing repo lesson): the agent writes nodes via its own MCP connection; the tick re-reads the graph. NOTE the cross-process visibility fix: `conn.commit()` immediately before the post-headless read so the tick's connection sees the agent's committed rows (see `patterns.find_patterns_tick`).
- **Triage lifecycle via free-text status** (no migration): A used `Pattern.status` open -> confirmed/dismissed + a `triage_pattern` MCP tool. B can do the same for `ArchDebt`.

### Substrate B reads/writes (already in the schema - likely NO migration needed)

- **`arch_debt` table already exists** (empty): columns `id, type(=ArchDebt), status, severity, owner, created_at, last_touched, body, summary, tags, scope`. `status` is free-text (no CHECK) - reuse for the triage lifecycle.
- **Reads:** `goal`, `module`, `file` (these tables exist), `spec`, `decision`, and the `Pattern` nodes A now produces.
- **Relations (valid types):** `observed-in`, `references`, `derived-from`, `supersedes`, `depends-on`, `caused-by`, `touches` - enough to link an `ArchDebt` to the modules/specs it spans and to the Patterns/findings that evidenced it. Link direction convention (from A): link FROM the new node TO its evidence, then read with `relations.neighbors(conn, node_id, "<rel>", "out")`.
- **`nodes.create_node(conn, "ArchDebt", status=, owner=, body=, ...)`**, `nodes.get_node`, `nodes.update_node`, `relations.link_nodes`, `relations.neighbors` - same API A used.

### Design forks to resolve IN B's brainstorm (do not pre-decide)

1. **Cadence trigger:** time-based (every N days, cron/`/loop`-driven) vs event-based (every K merged tasks). The single-tick model supports either; B reads the trigger condition from the graph. (The whole system is stateless-single-tick + cadence-owned-externally - no daemons.)
2. **Architectural-map tripwire - the highest-risk, least-specified piece.** What IS the "map" (a stored structural snapshot: module/dependency graph? a hash of some shape?) and what trips it (drift past a threshold)? This needs a concrete definition. Budget the most design time here.
3. **Alignment-vs-Goal scoring:** how to detect drift from the original `Goal` without false alarms. What's the signal, what's the threshold, what does a "drift detected" output look like (a Finding? an ArchDebt? a non-blocking diagnostic)?
4. **Reviewer incentive isolation:** the PRD stresses the arch-reviewer's only incentive is finding shape problems, not shipping. How is that encoded in the agent prompt (mirror the contrarian/code-reviewer asymmetry)?
5. **Does B read A's Patterns?** B is more valuable consuming `Pattern` nodes (a recurring pattern often signals architectural debt), but it can ship reading raw findings/modules if needed. Decide the coupling.

### The dogfooding decision reopens at B (read before choosing execution)

A was built with `superpowers-extended-cc:subagent-driven-development`, NOT the project's own headless orchestrator - because the orchestrator's reviewable unit is one-task-per-spec and it runs parallel disjoint-scope worktrees, which fights a sequential shared-file plan. See memory `phase3_execution_via_subagents_not_orchestrator`. If B's work can be shaped as **orthogonal one-spec-per-unit tasks**, B is a candidate to actually dogfood `orchestrate.tick` / the `launch-build` flow. Otherwise use subagent-driven-development again. Decide during planning.

## Conventions & gotchas (carry over from A)

- **Run pytest FROM `mcp-server/`** with `./.venv/Scripts/python.exe`. Pure helpers are fast-unit-tested; only real `claude -p` calls are `llm`-marked and excluded from the default suite. The fast suite is the gate; the `llm` e2e is the exit-gate proof.
- **Module style:** `conn` first arg; `nodes`/`relations` helpers `conn.commit()` internally. `_now()` = `datetime.now(timezone.utc).isoformat(timespec="seconds")`.
- **Never-raise contract** for anything cron/`/loop`-driven (mirror `orchestrate.tick` / `find_patterns_tick`); a direct user/agent action (like a triage call) SHOULD raise on misuse.
- **No new runtime dependency, prefer no schema migration** (A added neither). If B genuinely needs a new table/column, it's a `_migrate_to_v4` in `migrations.py` (next schema version is 4) - but check whether `arch_debt` + existing relations already suffice (they likely do).
- **ASCII-only** in every source/agent/command string literal (PS 5.1 cp1252 gotcha). Verify new `.md` files with a byte-scan.
- **Model preference:** dispatch subagent-driven implementers AND reviewers at `model: opus` (memory `subagent_model_opus`).
- **Skill policy** (`CLAUDE.md`): only auto-invoke `superpowers-extended-cc` plugin skills in this repo. **Ignore `norns-loop-review/` entirely.**
- **Git:** work on a feature branch off `main` (not a separate `.worktrees/` dir - the venv editable-install pins to the source path and subagents share the working dir; an in-place branch is the working isolation here). Two-stage review per task (spec compliance, then code quality), plus a final whole-implementation review, then `finishing-a-development-branch`.

## Tracked follow-up (not B-specific, but B may want it first)

- ~~**`PRAGMA busy_timeout` is NOT set in `db.connect`**~~ **RESOLVED 2026-05-25** (rung 0, see Update above): `db.connect` now sets `PRAGMA busy_timeout = 5000`. Cross-process contention now waits instead of failing fast with `database is locked`. (The `conn.commit()` barrier in `patterns.find_patterns_tick` is still load-bearing for read-after-write visibility and remains.)

## Process reference (how A was built, repeat for B)

brainstorming (resolve the forks above) -> design spec in `docs/superpowers/specs/YYYY-MM-DD-phase-3-arch-review-design.md` -> `writing-plans` -> `subagent-driven-development`: fresh implementer subagent per task (opus), two-stage review after each (spec compliance, then code quality), final whole-implementation review, then `finishing-a-development-branch` -> PR. Verify reports by reading the diff (one A implementer narrated correctly but reviews still caught a real cross-process-visibility gap and a `--scope ''` command-doc bug before merge - the review gates earn their keep).

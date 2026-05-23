# Agentic Engineering System

A self-improving engineering system, packaged as a Claude Code plugin.

This repo is the upstream for [`GhostlyGawd/agentic-engineering`](https://github.com/GhostlyGawd/agentic-engineering).
Phase 0 (foundations) is shipped. Phases 1-4 are planned; see the PRD for the
full picture.

## What this is

The plugin gives a Claude Code session a **typed knowledge graph** of every
Goal, Spec, Task, Decision, Bug, Finding, Pattern, Module, File, Review, Retro,
and ArchDebt the project has accumulated. Specs are gated by a falsifiability
validator: a Spec cannot dispatch unless every acceptance criterion names a
runnable verification command (or a runtime signal) **and** the spec includes
a named feedback loop with both an observable signal and a fix path.

State lives in `./.agentic/graph.db` (SQLite). All durable writes go through
the bundled stdio MCP server.

> **Correction (2026-05-19):** the `agentic-graph` MCP server is now registered
> **per-machine** by `/agentic:init`, which writes a git-ignored `.mcp.json`
> pointing at the plugin venv's interpreter (`<venv>\python.exe -m
> agentic_mcp.server`). Earlier builds shipped a bare `agentic-mcp` command that
> was not on PATH and **never connected** to Claude Code — so restart Claude Code
> after init and confirm with `claude mcp list`. The live `llm` e2e likewise
> stages this registration into its test project (`--mcp-config`); with it, all
> three real-agent scenarios pass deterministically. See
> `docs/plans/2026-05-19-phase-1.5-mcp-connection-defects.md`.

See `agentic-engineering-system-prd-v3.md` (in this repo root) for the full
PRD: motivation, core mechanics, gating decisions, and the Phase 0 - Phase 4
roadmap.

## Phase 0 status

| Area                                | Status |
|-------------------------------------|--------|
| Plugin manifest + MCP registration  | shipped |
| SQLite schema (14 entity tables + relations + indexes) | shipped |
| Entity CRUD (create_node, update_node, get_node)       | shipped |
| Relations (link_nodes + neighbors)  | shipped |
| Queries (query_graph, get_required_reads, walk_down)   | shipped |
| Findings (log_finding, mark_criterion_satisfied)       | shipped |
| Falsifiability + feedback-loop validators              | shipped |
| Scope auto-inference                | shipped |
| stdio MCP server (10 tools)         | shipped |
| Spec template + 3 worked examples   | shipped |
| `skills/router/`, `skills/spec-writing/`               | shipped |
| `agents/builder.md`, `agents/spec-checker.md`          | shipped |
| `/agentic:init`, `/agentic:detect-conflicts`, `/agentic:import-spec` | shipped |
| SessionStart hook (Windows / PowerShell)               | shipped |
| Phase 0 bootstrap exit-gate test    | passing |

**Shipped in Phase 1:** code-reviewer + contrarian roles + four-tier severity loop
+ spec-writer agent + critical-loop persistence + build/review commands (see below).

**Shipped in Phase 2:** stateless single-tick orchestrator, headless worker/reviewer
pool, serial-when-shared scope isolation, git worktree dispatch, scheduled weeding,
trust-weighting calibration, schema v3 (`claim` + `calibration` tables), and 7 new
MCP tools (see below).

**Deferred to later phases:** `sqlite-vec` / vec0 (Phase 3), pattern-finder +
architectural-review + meta-graph (Phase 3), self-improvement + reviewer calibration
learning beyond trust-weighting (Phase 4).

Phase 0 is **Windows-only**. The SessionStart hook is PowerShell 5.1; the
walk-up test is `skipif`-gated on `sys.platform != 'win32'`. A portable POSIX
hook is Phase 1+ work.

## Phase 1: Build pipeline + review loop

Phase 1 ships the four-role review team, autonomous critical loop, spec-writer
agent, and the `/agentic:dispatch` + `/agentic:review-pr` + `/agentic:new-spec`
commands.

### New entity: CriticalLoop

The `critical_loop` table tracks a persistent loop state for every Critical
finding. A `user_version`-gated migration (`migrations.py`) upgrades an existing
Phase 0 `graph.db` in place: it adds the `critical_loop` table plus
`dispatched_at` on `spec` and `criterion_index`, `loop_iteration`, `triage` on
`finding`. Running the migration twice is a no-op.

### New MCP tools (8 added; Phase 1 total: 18)

| Tool | Purpose |
|------|---------|
| `dispatch_spec` | Stamp a Spec as dispatched; locks its criteria. Idempotent. Create a superseding Spec to change criteria after dispatch. |
| `start_critical_loop` | Open a CriticalLoop tracking a Critical finding. |
| `advance_critical_loop` | Increment iteration count; fires `diagnostic_fired_at` once at iteration 3 (not re-stamped on 4+). |
| `resolve_critical_loop` | Mark a CriticalLoop resolved; sets `resolved_at`. |
| `get_open_loops` | List open CriticalLoops, optionally by scope. Survives cross-session reconnect. |
| `record_triage` | Set `fix-in-pr` or `backlog` on an Important finding (Important-only by design). |
| `log_retro` | Write a Retro tagged by `failed_layer`; optionally link `caused-by` a finding. |
| `detect_stability_contradiction` | Log a soft Pattern when a Critical hits a byte-identical file that the reviewer previously approved. Records only; never suppresses the Critical. |

### Updated and new agents

| Agent | Role |
|-------|------|
| `agents/builder.md` | Extended with **loop-fix mode** (design L-8): read the finding and the diagnostic if `diagnostic_fired_at` is set; fix the root cause, not the symptom; one commit per iteration with `Loop-Id` + `Loop-Iteration` trailers; write a `Retro` via `log_retro` on resolution. The builder does NOT advance or resolve the loop -- that is the command's job. |
| `agents/code-reviewer.md` | New. Emits four-tier severity findings (Critical/Important/Suggested/Strength); for every Important, records a `fix-in-pr`/`backlog` triage via `record_triage`. Runs blind to the contrarian (gate-then-parallel, design L-7). |
| `agents/contrarian.md` | New. Asymmetric assume-it-is-wrong stance: hunts hidden assumptions, architectural mismatch, scaling/concurrency traps, and security-model gaps -- not line-level style. Runs blind to the code-reviewer. |
| `agents/spec-writer.md` | New. Reads `skills/spec-writing/SKILL.md`, runs the Socratic pass, calls `validate_spec` inline, retries up to 5 times on rejection, escalates to the user at the cap. Never returns a spec that `validate_spec` rejected. |

### New commands

| Command | Purpose |
|---------|---------|
| `/agentic:dispatch <spec>` | Re-validate the spec, stamp `dispatched_at`, kick the builder at iteration 1. Criteria are immutable after dispatch. |
| `/agentic:review-pr` | Full review loop: auto-detect target (PR diff or working tree); gate (spec-checker) then parallel (code-reviewer + contrarian, blind); classify severity; manage the critical loop; fire the 3-iteration diagnostic; close with Strength + Retros. References `detect_stability_contradiction`. |
| `/agentic:new-spec` | Dispatch the spec-writer subagent; report the created Spec id or the retry-cap escalation. |

## Phase 2: Orchestration & Parallelism

Phase 2 ships the stateless single-tick orchestrator, headless worker/reviewer
pool, serial-when-shared scope isolation, git worktree dispatch, scheduled graph
weeding, and per-role trust-weighting calibration.

### Orchestrator model

The orchestrator is **stateless and single-tick.** Each `/agentic:orchestrate --once`
invocation is a fresh process: it hydrates all state from `graph.db`, does one tick,
and exits. `/loop` or cron owns the cadence. No long-lived session accumulates a
transcript.

Each tick runs these steps in order:

1. **Weed** - flag dispatched Specs untouched > 14 days (configurable) via `flag_stale`.
   Never auto-closes; every stale Spec is surfaced for user triage. (Node-level
   weeding across all entity types exists as `weeding.find_stale_nodes` but is not
   yet wired into the tick - deferred.)
2. **Compute the ready set** - Tasks whose `depends-on` deps are all resolved and
   whose parent Spec is dispatched.
3. **Overlap filter (serial-when-shared)** - `detect_overlap` partitions the ready
   set into a non-overlapping runnable batch and a held set. Tasks that share scope
   with a held Claim wait for a later serial tick.
4. **Dispatch** - for each open pool slot (default 3), create a git worktree + branch
   and spawn a headless worker (`claude -p` subprocess, `builder` agent).
5. **Harvest, review, merge** - worker CLEAN -> handoff to the reviewer step. The
   orchestrator agent drives the full Phase-1 review panel (spec-checker gate, then
   code-reviewer + contrarian) via tool calls; the `orchestrate.py` Python tick
   exposes a `review_fn` seam for this and ships a thin CLEAN-returning default that
   the e2e and agent override. Reviewer CLEAN -> merge in DAG order; `release_claim`.
   Conflicts and escalations are surfaced to the user and never auto-resolved.
6. **Calibrate** - record per-role outcomes via `record_outcome`; if a threshold
   crosses, call `adjust_trust` (sets/clears `distrusted`, changes scheduling for
   that role).
7. **Exit** - write the tick summary. The graph fully reflects progress.

### Headless worker/reviewer pool

Workers and reviewers run as ephemeral `claude -p --permission-mode bypassPermissions`
subprocesses, each in an isolated git worktree. The Pool enforces a per-process
timeout with process-tree kill on hang. One failing job never aborts the batch.

Each worker result is a structured `{task_id, ok, error}` dict read back from the
subprocess - orchestrator context never retains worker transcripts.

Workers reuse the Phase-1 agents (`builder.md`, `code-reviewer.md`,
`contrarian.md`, `spec-checker.md`), now invoked headlessly. The `headless.py`
module (promoted from `tests/llm_harness.py`) provides the subprocess launch,
`--output-format json` result parse, timeout, UTF-8 decode, and process-tree kill.

### New entities (schema `user_version` 3)

- **`claim`** table: `id, task_id, scope_paths (JSON array), worktree, branch,
  status (held|released), created_at`. Backs serial-when-shared and worktree
  bookkeeping.
- **`calibration`** table: `role TEXT PRIMARY KEY, observations, hits, misses,
  score REAL, last_adjusted_at, distrusted INTEGER (0|1)`. One row per role.
- **`spec.stale_flagged_at`** column: weeding output.

The schema v3 migration runs via the existing versioned-migration framework; it is
idempotent (re-running is a no-op).

### New command and agent

| Entity | Description |
|--------|-------------|
| `/agentic:orchestrate` | Tick driver. Args: `--once` (convention flag signaling single-tick intent for `/loop`/cron callers; the CLI always runs exactly one tick), `--pool N` (default 3), `--weed-days N` (default 14). Implemented in `orchestrate.py` as `python -m agentic_mcp.orchestrate --once`. |
| `agents/orchestrator.md` | System prompt for the scheduler role. Computes the DAG, detects overlap, weeds, calibrates, surfaces escalations. Implements nothing. |

### New MCP tools (7 added; Phase 2 total: 25)

| Tool | Purpose |
|------|---------|
| `claim_scope` | Record a Task's claimed paths; returns a conflict result if they overlap an open held Claim. Returns a `claim_id` UUID (not the task id) for use with `release_claim`. |
| `release_claim` | Release a Claim on task completion/merge. Takes the `claim_id` UUID from `claim_scope`. |
| `detect_overlap` | Given a ready-task candidate list (`{task_id, scope_paths}` dicts), return the maximum non-overlapping batch (the scheduler's core serial-when-shared query). |
| `flag_stale` | Flag dispatched Specs stale-for-triage (weeding output). Sets `spec.stale_flagged_at`. |
| `record_outcome` | Append a hit or miss to a role's calibration record. |
| `get_calibration` | Read a role's current score and `distrusted` flag (orchestrator consults before scheduling reviews). |
| `adjust_trust` | On threshold-crossing: set or clear `distrusted`, stamp `last_adjusted_at`. Satisfies the exit gate when it fires. |

### Phase 2 exit gate

**PRD gate:** two teams build in parallel on orthogonal tasks without merge
collisions; graph weeding runs on schedule; at least one calibration adjustment has
fired.

The live exit-gate test is `tests/test_phase2_e2e.py` (marked `llm`; three
scenarios: parallel orthogonal builds + merge, deliberate stale weed, scripted
reviewer miss driving `adjust_trust`). The fast suite covers all unit logic (overlap
detection, DAG merge order, weeding thresholds, calibration math, claim lifecycle,
schema v3 migration idempotency, Pool wrapper with a stubbed launcher).

### Running the test suite

```powershell
# Fast suite (no live agent needed) -- the fast suite:
cd mcp-server
.\.venv\Scripts\python.exe -m pytest -m "not llm" -q

# LLM exit-gate (requires a live claude CLI session):
.\.venv\Scripts\python.exe -m pytest -m llm -q
```

The `llm` marker gates two exit-gate suites:

- **`test_phase1_e2e.py`** - three real-agent scenarios: stubborn Critical loop
  (diagnostic at iteration 3, resolve at iteration 4, Retro tagged `implementation`);
  mixed-severity auto-triage; contrarian catching a distinct architectural flaw.
- **`test_phase2_e2e.py`** - three orchestration scenarios: scripted misses driving
  `adjust_trust` to set `distrusted=1` (deterministic); a deliberate stale weed
  (deterministic); two orthogonal Specs built in parallel worktrees with merge. Only
  the parallel-build scenario needs a live `claude`; the calibration and weeding
  scenarios are deterministic but live under the `llm` marker.

The fast suite covers everything else and is the default
(`addopts = "-m \"not llm\""` in `pyproject.toml`).

## Install (from a clone of this repo)

Requires Python 3.12 and PowerShell 5.1+ on Windows.

```powershell
git clone https://github.com/GhostlyGawd/agentic-engineering.git
cd agentic-engineering
cd mcp-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -v
```

All 145 fast tests should pass (the `llm`-marked exit-gate tests are
deselected by default; run them with `pytest -m llm` against a live `claude`
CLI session).

Then register the MCP server for this checkout and reload Claude Code:

    # writes a .mcp.json pointing at this venv's python (per-machine, git-ignored)
    .\.venv\Scripts\python.exe -m agentic_mcp.init_project --root ..
    # restart Claude Code, then confirm:
    claude mcp list   # agentic-graph ... - Connected

To install as a Claude Code plugin: `/plugin install` from the repo root, then
let the SessionStart hook walk up to find `./.agentic/` in any subdirectory.

## Bootstrapping a project

In any project where you want the system active:

```
/agentic:init                       # scaffolds .agentic/ at cwd
/agentic:detect-conflicts           # informational - never modifies other plugins
/agentic:import-spec <path-or-text> # bridge if you wrote a plan elsewhere
```

`/agentic:init` accepts an optional scope-mode argument (`isolated` default,
`workspace`, or `personal`).

## Writing a Spec

Start from `templates/spec.md`. The file ships with three worked examples that
all pass `validate_spec`:

1. **Trivial:** `slugify(s)` utility
2. **Real feature:** `/agentic:status` command
3. **Bug fix:** sqlite-vec failure on system Python

`skills/spec-writing/SKILL.md` walks through the Socratic intent-clarification
pass to run before locking the spec.

## MCP tool surface (25 tools)

**Phase 0 (10):** `create_node`, `update_node`, `get_node`, `link_nodes`,
`query_graph`, `get_required_reads`, `log_finding`, `mark_criterion_satisfied`,
`validate_spec`, `infer_scope`.

**Phase 1 (8):** `dispatch_spec`, `start_critical_loop`, `advance_critical_loop`,
`resolve_critical_loop`, `get_open_loops`, `record_triage`, `log_retro`,
`detect_stability_contradiction`.

**Phase 2 (7):** `claim_scope`, `release_claim`, `detect_overlap`, `flag_stale`,
`record_outcome`, `get_calibration`, `adjust_trust`.

See `skills/router/SKILL.md` for what each tool does.

## How to extend

`docs/plans/2026-05-17-phase-0-foundations.md` is the Phase 0 implementation
plan that was actually executed (with the `.tasks.json` sidecar holding the
22-task dependency graph). Future phases will follow the same pattern: a plan
file under `docs/plans/`, executed by Claude Code's `executing-plans` skill or
its multi-agent successor.

## License

MIT.

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

**Deferred to later phases:** `sqlite-vec` / vec0 (Phase 3), orchestrator +
parallelism + git worktrees (Phase 2), pattern-finder + architectural-review +
meta-graph (Phase 3), self-improvement + reviewer calibration (Phase 4).

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

### Running the test suite

```powershell
# Fast suite (no live agent needed) -- the fast suite:
cd mcp-server
.\.venv\Scripts\python.exe -m pytest -m "not llm" -q

# LLM exit-gate (requires a live claude CLI session):
.\.venv\Scripts\python.exe -m pytest -m llm -q
```

The `llm` marker gate (`test_phase1_e2e.py`) exercises three real-agent scenarios:
stubborn Critical loop (diagnostic at iteration 3, resolve at iteration 4, Retro
tagged `implementation`); mixed-severity auto-triage; and contrarian catching a
distinct architectural flaw. The fast suite covers everything else and is the
default (`addopts = "-m \"not llm\""` in `pyproject.toml`).

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

All 102 fast tests should pass (the 4 `llm`-marked exit-gate tests are
deselected by default; run them with `pytest -m llm` against a live `claude`
CLI session).

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

## MCP tool surface (18 tools)

**Phase 0 (10):** `create_node`, `update_node`, `get_node`, `link_nodes`,
`query_graph`, `get_required_reads`, `log_finding`, `mark_criterion_satisfied`,
`validate_spec`, `infer_scope`.

**Phase 1 (8):** `dispatch_spec`, `start_critical_loop`, `advance_critical_loop`,
`resolve_critical_loop`, `get_open_loops`, `record_triage`, `log_retro`,
`detect_stability_contradiction`.

See `skills/router/SKILL.md` for what each Phase 0 tool does.

## How to extend

`docs/plans/2026-05-17-phase-0-foundations.md` is the Phase 0 implementation
plan that was actually executed (with the `.tasks.json` sidecar holding the
22-task dependency graph). Future phases will follow the same pattern: a plan
file under `docs/plans/`, executed by Claude Code's `executing-plans` skill or
its multi-agent successor.

## License

MIT.

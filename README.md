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
| End-to-end exit-gate test           | passing |

**Deferred to later phases:** `sqlite-vec` / vec0 (Phase 3), code-reviewer +
contrarian roles + four-tier severity loop (Phase 1), orchestrator + parallelism
+ git worktrees (Phase 2), pattern-finder + architectural-review + meta-graph
(Phase 3), self-improvement + reviewer calibration (Phase 4).

Phase 0 is **Windows-only**. The SessionStart hook is PowerShell 5.1; the
walk-up test is `skipif`-gated on `sys.platform != 'win32'`. A portable POSIX
hook is Phase 1+ work.

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

All 65 tests should pass.

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

## MCP tool surface (10 tools)

`create_node`, `update_node`, `get_node`, `link_nodes`, `query_graph`,
`get_required_reads`, `log_finding`, `mark_criterion_satisfied`, `validate_spec`,
`infer_scope`.

See `skills/router/SKILL.md` for what each does.

## How to extend

`docs/plans/2026-05-17-phase-0-foundations.md` is the Phase 0 implementation
plan that was actually executed (with the `.tasks.json` sidecar holding the
22-task dependency graph). Future phases will follow the same pattern: a plan
file under `docs/plans/`, executed by Claude Code's `executing-plans` skill or
its multi-agent successor.

## License

MIT.

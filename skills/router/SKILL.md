---
name: router
description: Entry point for the Agentic Engineering System. Names the graph tools, the spec gate, and the active build flow so any subagent in this project knows where to look first.
---

# Router - Agentic Engineering System (Phase 0 + Phase 1 + Phase 2)

This project uses a self-contained Claude Code plugin. State lives in a SQLite graph
at `./.agentic/graph.db`. The only path to durable state is the bundled MCP server's
tools - there is no other surface that persists work.

## Where to look

- **Spec template:** `templates/spec.md` (with 3 worked examples).
- **Spec-writing guidance:** `skills/spec-writing/SKILL.md`.
- **Build subagents (Phase 0):** `agents/builder.md`, `agents/spec-checker.md`.
- **Review subagents (Phase 1):** `agents/code-reviewer.md`, `agents/contrarian.md`, `agents/spec-writer.md`.
- **Orchestration (Phase 2):** `agents/orchestrator.md`.
- **Slash commands (Phase 0):** `/agentic:init`, `/agentic:detect-conflicts`, `/agentic:import-spec`.
- **Slash commands (Phase 1):** `/agentic:dispatch`, `/agentic:review-pr`, `/agentic:new-spec`.
- **Slash commands (Phase 2):** `/agentic:orchestrate` (args: `--once`, `--pool N`, `--weed-days N`).

## MCP tool surface (25 tools total)

The `agentic-graph` MCP server exposes 25 tools. Every durable write must go
through one of them.

### Phase 0 tools (10)

| Tool                       | Purpose                                              |
|----------------------------|------------------------------------------------------|
| `create_node`              | Create a Goal, Epic, Task, Subtask, Spec, Decision, Bug, Finding, Pattern, Module, File, Review, Retro, or ArchDebt node. |
| `update_node`              | Update an existing node's fields (bumps last_touched). |
| `get_node`                 | Fetch a single node by id.                           |
| `link_nodes`               | Create a typed relation (implements, depends-on, blocks, supersedes, caused-by, observed-in, touches, references, derived-from). |
| `query_graph`              | Filtered node query (by type, status, severity, scope). |
| `get_required_reads`       | Resolve a Spec's `required_reads` list into full node dicts. |
| `log_finding`              | Create a Finding attached to a parent node; inherits parent scope. |
| `mark_criterion_satisfied` | Mark a Spec acceptance criterion satisfied with required evidence. |
| `validate_spec`            | Run the falsifiability + feedback-loop gates on a Spec. |
| `infer_scope`              | Heuristically infer a scope tag from body/parent/cwd/files. |

### Phase 1 tools (8)

| Tool                           | Purpose                                              |
|--------------------------------|------------------------------------------------------|
| `dispatch_spec`                | Stamp a Spec as dispatched; locks its criteria. Idempotent. |
| `start_critical_loop`          | Open a CriticalLoop tracking a Critical finding. |
| `advance_critical_loop`        | Increment iteration count; fires `diagnostic_fired_at` once at iteration 3. |
| `resolve_critical_loop`        | Mark a CriticalLoop resolved; sets `resolved_at`. |
| `get_open_loops`               | List open CriticalLoops, optionally by scope. Survives cross-session reconnect. |
| `record_triage`                | Set `fix-in-pr` or `backlog` on an Important finding (Important-only by design). |
| `log_retro`                    | Write a Retro tagged by `failed_layer`; optionally link `caused-by` a finding. |
| `detect_stability_contradiction` | Log a soft Pattern when a Critical hits a byte-identical file the reviewer previously approved. |

### Phase 2 tools (7)

| Tool               | Purpose                                              |
|--------------------|------------------------------------------------------|
| `claim_scope`      | Record a Task's claimed paths (modules/files it will touch); returns a conflict result if they overlap an open held Claim. Returns a `claim_id` UUID (not the task id) for use with `release_claim`. |
| `release_claim`    | Release a Claim on task completion/merge. Takes the `claim_id` UUID from `claim_scope`. |
| `detect_overlap`   | Given a ready-task candidate list (`{task_id, scope_paths}` dicts), return the maximum non-overlapping batch (the scheduler's core serial-when-shared query). |
| `flag_stale`       | Mark Specs/nodes stale-for-triage (weeding output). Sets `spec.stale_flagged_at` on Specs. Never auto-closes. |
| `record_outcome`   | Append a hit or miss to a role's calibration record (hit: Critical confirmed or Strength validated; miss: stability contradiction or missed Critical). |
| `get_calibration`  | Read a role's current smoothed score and `distrusted` flag. The orchestrator consults this before scheduling reviews. |
| `adjust_trust`     | On threshold-crossing: set or clear `distrusted`, stamp `last_adjusted_at`. A `distrusted` role requires a second reviewer and its Criticals do not merge-block alone. Satisfies the Phase 2 exit gate when it fires. |

## How dispatch works in Phase 0

1. A Spec is written using `templates/spec.md` (or imported via `/agentic:import-spec`).
2. `validate_spec` runs as a hard gate - un-falsifiable criteria or a missing
   feedback loop block dispatch.
3. The **builder** subagent reads the spec, the relevant graph slice (via
   `get_required_reads` and `query_graph`), and the relevant module skill file
   (if any). It implements, tests, and records its work.
4. The **spec-checker** subagent receives only the spec and the artifact - never
   the builder's prose. It runs each criterion's `verify` command, calls
   `mark_criterion_satisfied` (with evidence) for each pass, and logs `Finding`s
   for failures.
5. The cycle ends. Findings remain in the graph for future tasks to surface.

## How orchestration works in Phase 2

Each `/agentic:orchestrate --once` invocation is one stateless tick. The orchestrator
hydrates entirely from `graph.db`, computes the DAG ready set, filters overlapping
scopes (`detect_overlap`), claims non-overlapping tasks (`claim_scope`), spawns
headless workers into isolated git worktrees, harvests structured results, drives the
Phase-1 review panel headlessly, merges CLEAN branches in DAG order
(`release_claim`), calibrates per-role trust (`record_outcome` / `get_calibration` /
`adjust_trust`), and exits. `/loop` or cron owns the cadence.

## What's deferred to later phases

- Pattern-finder, periodic architectural review, cross-project meta-graph (Phase 3).
- `sqlite-vec` / vec0 embeddings (Phase 3).
- Self-improvement / reviewer-calibration learning beyond trust-weighting (Phase 4).
- The `/agentic:find-patterns` command (Phase 3).

## Scope semantics

Every node has a `scope` field (auto-inferred via `infer_scope` or explicit).
Scope is a soft tag - it does not block dispatch. It is used by the pattern-finder
in later phases to correlate signals within or across repos/modules.

## Build philosophy

You have access to a typed graph of every Finding, Decision, Bug, and Pattern
this project has accumulated. That memory is not something a single human engineer
can hold. Use it: query before guessing, link related nodes, and write what you
observe so the next agent inherits the context.

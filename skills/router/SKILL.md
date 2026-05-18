---
name: router
description: Entry point for the Agentic Engineering System. Names the graph tools, the spec gate, and the active build flow so any subagent in this project knows where to look first.
---

# Router - Agentic Engineering System (Phase 0)

This project uses a self-contained Claude Code plugin. State lives in a SQLite graph
at `./.agentic/graph.db`. The only path to durable state is the bundled MCP server's
tools - there is no other surface that persists work.

## Where to look

- **Spec template:** `templates/spec.md` (with 3 worked examples).
- **Spec-writing guidance:** `skills/spec-writing/SKILL.md`.
- **Build subagents (Phase 0):** `agents/builder.md`, `agents/spec-checker.md`.
- **Slash commands (Phase 0):** `/agentic:init`, `/agentic:detect-conflicts`, `/agentic:import-spec`.

## MCP tool surface

The `agentic-graph` MCP server exposes these 10 tools. Every durable write must go
through one of them.

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

## What's deferred to Phase 1+

- Code-reviewer + contrarian roles, four-tier severity loop, critical-loop persistence.
- Orchestrator, parallelism, git worktrees.
- Pattern-finder, architectural-review, meta-graph, cross-project patterns.
- The `/agentic:new-spec`, `/agentic:dispatch`, `/agentic:review-pr`,
  `/agentic:find-patterns` commands.

## Scope semantics

Every node has a `scope` field (auto-inferred via `infer_scope` or explicit).
Scope is a soft tag - it does not block dispatch. It is used by the pattern-finder
in later phases to correlate signals within or across repos/modules.

## Build philosophy

You have access to a typed graph of every Finding, Decision, Bug, and Pattern
this project has accumulated. That memory is not something a single human engineer
can hold. Use it: query before guessing, link related nodes, and write what you
observe so the next agent inherits the context.

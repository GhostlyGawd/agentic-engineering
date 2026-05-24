# Phase 3 Sub-project A: Pattern-finder (design)

> Status: Approved (brainstorming) 2026-05-24.
> Date: 2026-05-24. Base branch: `main`.
> First slice of Phase 3 (Meta-Review). Decomposition:
> `docs/plans/2026-05-24-phase-3-decomposition.md` (sub-projects A -> B -> C).
> Produces the `Pattern` half of the Phase 3 exit gate ("one real Pattern produced
> and triaged").

## Purpose

Turn the accumulating stream of `Finding` / `Bug` / `Retro` nodes into durable,
triageable `Pattern` nodes. Recurring problems ("the spec-checker keeps missing
async criteria", "three bugs all trace to one module") should become first-class
graph objects with an explainable evidence trail - not noise scattered across
individual findings.

This is the bottom-up meta-review layer. The top-down architectural-review layer
(sub-project B) and the cross-project meta-graph (sub-project C) are separate specs
and out of scope here.

## Goals / non-goals

**Goals**
- Detect recurrence across `finding`/`bug`/`retro` nodes within a scope and mint
  `Pattern` nodes with a `derived-from` evidence trail.
- Be safe to run on a schedule (idempotent; bounded LLM cost) AND on demand.
- Give Patterns a triage lifecycle so the exit-gate "produced AND triaged" is met.
- Reuse the established headless-agent machinery and the pure-core / stubbed-seam /
  `llm`-gated-e2e test split. No new runtime dependency. No schema migration.

**Non-goals (deferred, see "Out of scope")**
- `sqlite-vec` / vec0 vector similarity (designed-for as a future candidate source,
  not built).
- Cross-scope correlation and the cross-project meta-graph (sub-project C).
- Acting on Patterns (spawning ArchDebt/Spec, prompt/threshold edits) - that is
  sub-project B and Phase 4.

## Locked decisions (from the brainstorm)

1. **Hybrid detection.** A cheap deterministic pre-cluster over existing columns
   forms candidate groups; ONE headless LLM "confirm" pass per group names/judges
   it. vec0 is deferred and enters later purely as another candidate-source feeding
   the same grouping interface - no rework.
2. **Minting bar = 3.** A candidate group needs `>= 3` evidence nodes before it is
   sent to the confirm step. Mirrors the existing `DIAGNOSTIC_THRESHOLD == 3`.
3. **Confirm step mints via the graph (not stdout parsing).** The pattern-finder
   agent gets graph access (the working `stage_mcp_config` path) and itself calls
   `create_node` + `link_nodes` to mint a confirmed `Pattern`. The tick then DERIVES
   what happened by querying the graph. This honors the repo's "derive from the
   graph, never parse prose" lesson (same rationale as `_real_review` /
   `_verdict_from_graph`).
4. **Reject memory = dismissed-tombstone Pattern.** When the agent judges a group is
   not a real pattern, the tick mints a `Pattern` with `status='dismissed'`,
   `owner='system'`, linked `derived-from` the same evidence. Dedup (decision 6)
   then skips that evidence forever, bounding repeated LLM cost. Auditable.
5. **Triage = status lifecycle, no migration.** `Pattern.status` (free-text, no
   CHECK in `schema.sql`) carries `open -> confirmed | dismissed`. A confirmed
   Pattern may later link to a spawned ArchDebt/Spec (sub-project B).
6. **Idempotency by evidence coverage.** `candidate_groups` skips any group whose
   evidence set is already covered by an EXISTING `Pattern` of ANY status
   (confirmed, open, or dismissed-tombstone). This is the load-bearing correctness
   property for the scheduled path - confirmed and rejected groups alike stop
   churning.
7. **Within-scope only.** Grouping correlates within a single `scope` (default
   `isolated`). Cross-scope is sub-project C.
8. **Single-tick, cadence-owned-externally.** One `find_patterns_tick` serves both
   `/agentic:find-patterns` (on demand) and cron/`/loop` (scheduled). No daemon.
   Never-raise discipline, like `orchestrate.tick`.

## Architecture

```
finding / bug / retro nodes (within a scope)
        |
        v
[1] candidate_groups(conn, scope, min_size=3)     pure / deterministic / fast-tested
    - group by structural signal (parent_id, subtype, tag/file overlap, failed_layer)
    - drop groups < min_size
    - drop groups whose evidence is already covered by ANY existing Pattern (dedup)
    -> [{key, reason, evidence_ids}]
        |
        v
[2] confirm_fn(group, ...)                         seam: real = headless agent
    real path stages agents/pattern-finder.md + runs claude -p (stdin prompt) with
    graph access; the agent judges and, if real, mints the Pattern itself via
    create_node + link_nodes(derived-from)
        |
        v
[3] find_patterns_tick(conn, *, scope, db_path, confirm_fn, min_size)   never-raise
    - per group: snapshot existing Pattern ids -> run confirm_fn -> derive newly
      minted Pattern from the graph
    - if none minted -> tick writes a dismissed-tombstone Pattern (system)
    -> {minted: [...], dismissed: [...], considered: N, errors: [...]}
        |
        v
Pattern nodes (status='open')
        |
        v
[4] triage_pattern(conn, pattern_id, disposition)  open -> confirmed | dismissed
    surfaced by /agentic:find-patterns; exposed as an MCP tool
```

The shape is a deliberate copy of `orchestrate.py`: pure helpers compute everything
graph-dependent; a seam (`confirm_fn`, default `_real_confirm`) is the only thing
that touches `claude` and is stubbed in the fast suite; the driver is never-raise.

## Components

### 1. `patterns.candidate_groups(conn, scope=None, min_size=3) -> list[dict]`
Pure read. Returns candidate groups, each `{key, reason, evidence_ids}`.

- **Input set:** open `finding`, `bug`, `retro` nodes, filtered to `scope` when
  given (NULL scope is its own bucket; never matched against a named scope - same
  trap `_verdict_from_graph` documents about `parent_id` vs `scope`).
- **Grouping signals** (each yields candidate groups; a node may appear in more than
  one signal's groups, but dedup + tombstones prevent double-minting over time):
  - shared `parent_id` (multiple findings on the same spec/node)
  - shared `subtype` (e.g. `SystemUsabilityBug`) within the scope
  - overlapping `tags` (JSON array; treat shared tag / touched-file path as the key)
  - shared `failed_layer` (retros pointing at the same failed layer)
- **min_size:** drop any group with `< min_size` evidence nodes.
- **Dedup:** drop any group whose `evidence_ids` are already (fully, or above an
  overlap threshold - default: fully) covered by the `derived-from` evidence of an
  existing `Pattern` of ANY status. Implemented as a direct read of `relations`
  (`derived-from`, direction in) joined to `pattern`.
- **`reason`:** a short ASCII string naming the signal and key ("4 findings share
  parent_id S-123"); becomes the candidate's audit trail.
- No `claude`, no writes.

### 2. `confirm_fn` seam (`_real_confirm`, default)
Signature: `confirm_fn(group: dict, *, repo, mcp_config, source_root) -> None`.
The real path:
- Stages `agents/pattern-finder.md` into `<repo>/.claude/agents/` (reusing the same
  staging approach `_real_review` uses for the four review agents). Headless
  `claude -p` discovers project-level `.claude/agents/*.md`.
- Builds a prompt embedding the group's `evidence_ids` + each evidence node's body +
  the `reason`, instructing the agent to judge whether this is a genuine recurring
  pattern and, if so, mint ONE `Pattern` (status `open`) via `create_node` and link
  it `derived-from` every evidence id via `link_nodes`. If not genuine, mint nothing.
- Runs `headless.run_claude_headless(prompt, cwd=repo, mcp_config=mcp_config)`
  (prompt over stdin; the default 900s timeout is ample - the agent reads a handful
  of node bodies and makes one judgement, far lighter than a full review-pr loop;
  mcp_config from `stage_mcp_config` so the agent can reach the graph).
- Returns nothing; the tick derives the outcome from the graph.

Fast suite stubs `confirm_fn` entirely (no `claude`, no staging).

### 3. `patterns.find_patterns_tick(conn, *, scope=None, db_path=None, confirm_fn=_real_confirm, min_size=3, repo=".", source_root=None) -> dict`
Never-raise driver (no exception escapes; mirrors `orchestrate.tick`).
- Compute `groups = candidate_groups(conn, scope, min_size)`.
- If `groups` and `db_path is not None`: `mcp_config = stage_mcp_config(repo, db_path)`
  once (live path only; the no-jobs / no-db_path fast path stages nothing - same
  gating rule as `orchestrate.tick`).
- For each group, wrapped in try/except (errors collected, never raised):
  - snapshot the set of existing `Pattern` ids,
  - call `confirm_fn(group, ...)`,
  - on a CLEAN return (no exception), re-query: a new `open` Pattern linked
    `derived-from` this group's evidence -> record in `minted`; if the agent ran but
    minted nothing, the tick writes a dismissed-tombstone Pattern
    (`status='dismissed'`, `owner='system'`, `derived-from` the evidence) and records
    it in `dismissed`.
  - if `confirm_fn` RAISED, record the error and do NOT tombstone - the group is
    retried on the next tick (a crash/timeout is not a judgement that the group is
    not a pattern).
- Returns `{"minted": [...], "dismissed": [...], "considered": len(groups),
  "errors": [...]}`.

### 4. `patterns.triage_pattern(conn, pattern_id, disposition) -> None`
`disposition in {"confirmed", "dismissed"}`. Validates the node is a `Pattern`,
sets `status`. Raises `ValueError` on an unknown disposition or non-Pattern id
(this is a direct user/agent action, not the unattended tick, so raising is correct
here - contrast the tick's never-raise contract).

### 5. CLI + command + agent
- `patterns.main()` (argparse, modeled on `orchestrate.main()`): `--scope`,
  `--once`, `--repo`, resolves `db_path` via `db.resolve_db_path()`, calls
  `find_patterns_tick`, prints the result dict as JSON.
- `commands/find-patterns.md`: lists open Patterns (id, summary, evidence count) and
  runs a tick. The on-demand surface.
- `agents/pattern-finder.md`: the confirm-agent definition. Incentive framing: find
  GENUINE recurrence; reject coincidence; one Pattern per real group; cite evidence.
- An MCP tool wrapping `triage_pattern` (registered in `server.py`).

## Data flow & graph contract

- Reads: `finding`, `bug`, `retro` (filtered by `scope`); `pattern` + `relations`
  (`derived-from`) for dedup.
- Writes: `Pattern` nodes (by the agent on confirm; by the tick on tombstone) +
  `derived-from` relations from each Pattern to its evidence.
- Statuses used: `open` (just minted, awaiting triage), `confirmed` (triaged real),
  `dismissed` (triaged false OR system tombstone). All valid - `pattern.status` has
  no CHECK constraint.
- `derived-from` is an existing valid `relation_type`; no schema change.

## Error handling

- `find_patterns_tick`: per-group try/except; all errors land in `result["errors"]`;
  the tick never raises (safe under cron/`/loop`). A confirm-step crash/timeout for
  one group does not block the others and does NOT tombstone that group (so it is
  retried next tick - distinct from a clean "agent declined" which DOES tombstone).
- `candidate_groups`: pure read; a malformed `tags` JSON on a node is skipped, not
  fatal.
- `triage_pattern`: raises on misuse (direct action, fail loud).

## Testing strategy

- **Fast suite (no `claude`):**
  - `candidate_groups`: each signal groups correctly; `min_size` floor; scope filter
    (named scope vs NULL bucket); dedup against existing Patterns of each status;
    malformed-tags tolerance.
  - `find_patterns_tick`: never-raise (a `confirm_fn` that raises -> error recorded,
    no propagation); minted-vs-tombstone branch (stub `confirm_fn` that does/does not
    mint via a passed conn); `considered` count; no `.mcp.json` staged when
    `db_path is None` or no groups.
  - `triage_pattern`: `open->confirmed`, `open->dismissed`, raises on bad disposition
    / non-Pattern id.
  - agent-doc test (the existing `test_agent_docs.py` pattern) for
    `agents/pattern-finder.md` frontmatter.
- **`llm`-marked e2e** (`skipif(not headless.claude_on_path())`, excluded from the
  fast suite): seed a graph with `>=3` related findings (shared `parent_id`), run
  `find_patterns_tick` with the REAL `_real_confirm` and a real `db_path`; assert
  (a) one `Pattern` minted `status='open'`, (b) linked `derived-from` all evidence
  ids, (c) `triage_pattern(..., "confirmed")` moves it to `confirmed`. Structured
  graph assertions only; no prose inspection. Reuses the `_setup_git_repo` +
  `stage_mcp_config` patterns from `test_headless_loop_e2e.py`.

## File structure

| File | Change |
|------|--------|
| `mcp-server/src/agentic_mcp/patterns.py` | NEW. `candidate_groups`, `_real_confirm`, `find_patterns_tick`, `triage_pattern`, `main`. |
| `mcp-server/src/agentic_mcp/server.py` | Register a `triage_pattern` MCP tool. |
| `mcp-server/tests/test_patterns.py` | NEW. Fast unit + tick composition tests. |
| `mcp-server/tests/test_patterns_e2e.py` | NEW. `llm`-marked closed-loop e2e. |
| `agents/pattern-finder.md` | NEW. Confirm-agent definition. |
| `commands/find-patterns.md` | NEW. On-demand command. |

No migration, no new dependency, no change to `schema.sql`.

## Out of scope (recorded so it is not silently dropped)

- **vec0 / sqlite-vec** vector candidate source - future; the `candidate_groups`
  interface is the seam it will plug into.
- **Cross-scope correlation + cross-project meta-graph** - sub-project C.
- **Acting on confirmed Patterns** (spawn ArchDebt/Spec, edit prompts/thresholds) -
  sub-project B / Phase 4.
- **Overlap-threshold dedup tuning** - default is full-coverage dedup; a fuzzy
  overlap threshold is a later refinement if churn is observed.

## Exit criteria (this sub-project)

- Fast suite green (existing count + new `test_patterns.py`), 0 failures.
- `llm`-marked e2e proves: `>=3` related findings -> one `open` Pattern minted with
  a complete `derived-from` evidence trail -> triaged to `confirmed`.
- `/agentic:find-patterns` lists open Patterns and runs a tick.
- Satisfies the `Pattern` half of the Phase 3 PRD exit gate ("one real Pattern
  produced and triaged"). The `ArchDebt` half remains for sub-project B.

# Phase 3 (Meta-Review) - Decomposition

> Scoping/sequencing doc, NOT a design spec. Phase 3 in the PRD is six deliverables
> that cluster into three independent subsystems. Each sub-project gets its own
> brainstorm -> design spec -> implementation plan -> build cycle. This doc picks
> the seams between them, names the real design forks, and recommends an order.
> Written 2026-05-24, after the headless build+review loop merged.

## Phase 3 goal (from PRD v3)

> Pattern detection + periodic architectural review + drift checks + optional
> cross-project meta-graph.

**PRD exit gate:** at least one real `Pattern` AND one real `ArchDebt` produced and
triaged; the alignment check has run; if any user is in `workspace`/`personal`
scope mode, the meta-graph contains at least one cross-scope pattern.

## What already exists (substrate - do not rebuild)

- **Node tables:** `pattern` and `arch_debt` already exist in `schema.sql` (empty).
  `Retro`, `Finding` (with `subtype`, `parent_id`), `Bug`, `Goal` all exist.
- **Relations:** `derived-from`, `observed-in`, `references`, `caused-by`,
  `supersedes` are all valid `relation_type`s - enough to wire Patterns to their
  evidence and ArchDebt to the nodes it spans.
- **One Pattern minter already in code:** `stability.detect_stability_contradiction`
  creates `Pattern` nodes today. The pattern-finder is additive, not a rewrite.
- **Cadence model is settled:** stateless single-tick process; `/loop` or cron owns
  the cadence (the orchestrator's `--once` tick, `/worker`, `/reviewer`, `/pm` all
  follow this). Everything "scheduled"/"periodic" in Phase 3 MUST reuse this model -
  a fresh graph-hydrated process per tick, never a long-running daemon.
- **Headless agent machinery:** `headless.run_claude_headless` (stdin prompt),
  `stage_mcp_config`, staged-agents review path, and `_verdict_from_graph` all
  landed with the build+review loop. Sub-project B can reuse the staged-agents
  pattern wholesale.
- **MCP write surface:** `create_node`, `update_node`, `link_nodes`, `log_finding`,
  `log_retro`, `record_triage`, `query_graph` are live tools.

## What is NOT built

- No `sqlite-vec` / `vec0` (not installed; schema comment defers it to "when the
  pattern-finder needs it" - that "if" is sub-project A's first design fork).
- No `pattern-finder` or `architectural-reviewer` agent files.
- No `/agentic:find-patterns` command.
- No cross-project `meta.db`, no meta-graph sync.
- No alignment-check or arch-map-tripwire logic.

---

## Sub-project A - Pattern-finder (bottom-up)

**Purpose:** turn the accumulating stream of `Finding` / `Bug` / `Retro` nodes into
durable `Pattern` nodes ("the spec-checker keeps missing async criteria", "three
bugs all trace to the same module"), so recurring problems become first-class,
triageable graph objects instead of noise scattered across findings.

**PRD deliverables covered:** scheduled pattern-finder over Finding/Bug/Retro ->
Pattern nodes (within-scope first; cross-scope only if mode allows, high bar);
`/agentic:find-patterns` on-demand command.

**Graph I/O:** reads `finding`/`bug`/`retro` (filtered by `scope`); writes `Pattern`
nodes linked `derived-from` their evidence; respects scope boundaries (soft-tag
correlation per D-26).

**The central design fork - how does it detect patterns?**
1. **LLM-driven (no vec0):** a headless pattern-finder agent reads recent
   findings/bugs/retros for a scope and proposes Patterns. Simple, no new dep,
   matches the existing headless-agent pattern. Weakness: cost/scale as the graph
   grows; non-deterministic.
2. **Vector-similarity (sqlite-vec / vec0):** embed finding bodies, cluster by
   cosine similarity, then summarize clusters. Deterministic clustering, scales,
   but adds the `sqlite-vec` dependency + an embedding source + a vec0 virtual
   table migration (schema v4).
3. **Hybrid:** cheap structural pre-clustering (shared `parent_id`, shared
   `scope`, shared touched files, `subtype`) to form candidate groups, then an LLM
   pass only to name/confirm a Pattern. No embedding dep; bounds LLM cost.

   Recommendation to carry into A's brainstorm: **start hybrid (#3)**, treat vec0
   as a later enhancement gated on real data volume. The PRD assumes vec0 but the
   schema comment already hedges ("when the pattern-finder needs it").

**Dependencies:** none on B or C. Depends only on existing substrate. **Buildable
first.**

**Rough size:** medium. One agent file, one command, a `patterns.py` module (the
candidate-grouping + Pattern-minting helpers, fast-unit-testable), a single-tick
entry (`find-patterns --once`-style), and an `llm`-marked e2e.

---

## Sub-project B - Architectural review (top-down)

**Purpose:** hunt systemic/shape problems on a cadence with an incentive isolated
from shipping any single PR - the layer whose only job is to find architectural
debt, drift from the original Goal, and structural decay.

**PRD deliverables covered:** architectural-review agent with cadence + incentive
isolation; periodic alignment check against the original `Goal`; architectural-map
tripwire; produces `ArchDebt` nodes.

**Graph I/O:** reads `Goal`, `Module`/`File`, `Spec`, `Decision`, recent `Pattern`
nodes; writes `ArchDebt` nodes (linked `observed-in`/`references` the modules/specs
they span) and an alignment Finding/Retro when drift from the Goal is detected.

**Design forks:**
- **Cadence trigger:** time-based (every N days via cron) vs event-based (every K
  merged tasks). The single-tick model supports either; pick a trigger this layer
  reads from the graph.
- **Arch-map tripwire:** what is the "map", and what trips it? Likely a stored
  structural snapshot (module graph / dependency shape); the tripwire fires when
  the snapshot drifts past a threshold. Needs its own definition in B's brainstorm.
- **Reuse:** the staged-agents headless pattern (built for review-pr) transfers
  directly - stage an `architectural-reviewer.md` agent, run it headless with graph
  access, derive outcomes from the graph.

**Dependencies:** *soft* dependency on A - arch-review is more valuable when it can
read `Pattern` nodes, but it can ship reading raw findings if A isn't done.
**Buildable second** (or first if you prioritize the ArchDebt half of the exit gate).

**Rough size:** medium-large. New agent + cadence tick + alignment-check helper +
arch-map snapshot/diff logic + `llm`-marked e2e. The arch-map tripwire is the
least-specified piece and carries the most design risk.

---

## Sub-project C - Cross-project meta-graph

**Purpose:** let Patterns (and only Patterns) flow across projects into a shared
`~/.agentic/meta.db` (or a workspace path), so lessons learned in one repo surface
in another - but only when the user has opted into `workspace`/`personal` scope mode.

**PRD deliverables covered:** cross-project meta-graph populated only if scope mode
is `workspace`/`personal`; cross-scope pattern surfacing with a high robustness bar.

**Graph I/O:** reads `Pattern` nodes from per-project graphs; writes/syncs them into
`meta.db`; surfaces cross-scope patterns back with a higher confidence bar than
within-scope (D-13/D-26).

**Dependencies:** **hard dependency on A** - there are no `Pattern` nodes to sync
until the pattern-finder produces them. Also gated on scope-mode plumbing
(`scope.py` modes: `isolated` default / `workspace` / `personal`).

**Rough size:** small-medium, but **lowest immediate value:** default scope is
`isolated`, so for a single-repo dogfood this subsystem does nothing observable
until a second project opts into a shared scope. The PRD exit gate only requires it
"if any user is in workspace/personal mode."

**Recommendation:** **build last, or defer past Phase 3** unless you intend to run
two repos under a shared scope soon.

---

## Recommended ordering

```
A (pattern-finder)  ->  B (architectural review)  ->  C (meta-graph)
   independent            soft-dep on A               hard-dep on A
```

1. **A first.** Independent, leads the exit gate ("one real Pattern produced and
   triaged"), and forces the vec0-vs-LLM decision early where it's cheap to defer.
2. **B second.** Delivers the other half of the exit gate (one real `ArchDebt`) and
   the alignment check; reuses A's Patterns and the existing staged-agents machinery.
3. **C last / deferred.** Hard-depends on A's output and only activates under
   non-default scope mode. Defer unless a multi-repo shared scope is imminent.

A two-sub-project Phase 3 (A + B) satisfies the full PRD exit gate except the
conditional meta-graph clause.

## Cross-cutting conventions (apply to all three)

- **Single-tick, cadence-owned-externally.** No daemons. Each subsystem exposes an
  `--once` tick; `/loop` or cron drives it. Mirror `orchestrate.tick()`'s
  never-raise discipline for anything that runs unattended.
- **Scope-respecting.** Within-scope correlation is the default; cross-scope needs a
  higher bar (D-26). `scope.py` already centralizes this - reuse it.
- **Fast/slow test split.** Pure helpers (candidate grouping, snapshot diffing,
  verdict/threshold logic) are fast-unit-tested; only real `claude -p` calls are
  `llm`-marked and excluded from the default suite. Same split the whole repo uses.
- **sqlite-vec is one decision, made in A.** If A adopts vec0, it owns the
  `sqlite-vec` dependency + the schema v4 vec0 migration; B and C inherit it. If A
  stays LLM/hybrid, vec0 stays deferred.
- **No non-ASCII in source/command/agent string literals** (PS 5.1 cp1252 gotcha).

## Open questions to resolve in each sub-project's brainstorm

- **A:** vec0 vs LLM vs hybrid (lead: hybrid); what counts as "enough recurrence" to
  mint a Pattern; how Patterns get triaged (new status flow vs reuse `record_triage`).
- **B:** what exactly the architectural map is and what trips it; time- vs
  event-based cadence; how alignment-against-Goal is scored without false alarms.
- **C:** sync direction (push on tick vs pull on read); conflict/dedup of Patterns
  arriving from multiple repos; the cross-scope confidence bar.

## Next step

You pick the first slice (recommended: **A - pattern-finder**). That kicks off a
full brainstorm -> `docs/superpowers/specs/2026-05-24-phase-3-pattern-finder-design.md`
-> writing-plans cycle for that sub-project alone.

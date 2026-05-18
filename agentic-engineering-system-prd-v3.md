# Agentic Engineering System: PRD v3

> **Status**: Spec-writer ready. All gating decisions locked, recommendations ratified, edge cases resolved.
>
> **Audience**: Both human (you, collaborators) and Claude Code (build agent).
>
> **Scope**: Full system as the target, with a five-phase rollout naming Phase 0 as the MVP. Phase 0 ships *minimal* tactical guidance — full tactical polish is Phase 1+ work.

-----

## TL;DR

A self-improving engineering system, packaged as a Claude Code plugin, that treats each project as a small organization with persistent memory rather than a stateless pipeline. Three load-bearing ideas:

1. **Ground truth anchors at every layer** — no agent grades itself on subjective dimensions. Every "done" claim is checked against falsifiable criteria by a different context.
2. **A project knowledge graph as the central nervous system** — every finding, decision, bug, pattern, and follow-up is a typed node with relations. Indexed for top-down navigation and bottom-up pattern detection. SQLite + sqlite-vec, exposed via plugin-bundled MCP server.
3. **Periodic meta-review separate from per-PR review** — architectural and systemic flaws are hunted on a cadence by a layer whose only incentive is finding shape problems, not shipping the current PR.

The system aspires to **exceed any individual engineer on dimensions that compound with memory and time** (coverage, consistency, cross-time pattern detection, no-fatigue thoroughness, simultaneous multi-domain review) and to **complement human judgment** on novel reasoning where no prior pattern applies. Don't preemptively limit the ceiling; let real performance set it.

The plugin is fully self-contained. It does not depend on or reference any other plugin at runtime. Tactical practices (TDD, systematic debugging, audit, intent-clarification) are embedded as concise guidance inside our own subagent prompts. Other plugins coexist via Claude Code's namespacing without integration.

Optional cross-project pattern sharing is opt-in via per-project scope modes; default is isolated.

-----

## Problem Statement

Recurring failure modes in working with Claude Code at scale:

- **Self-marking homework**. A single agent implements and verifies its own work; errors surface only when the user catches them or production breaks.
- **Information loss across sessions**. Findings, follow-ups, blocking bugs, and "nice-to-haves" from one session evaporate when it ends.
- **Plans that look complete but aren't**. A plan is declared ready when prose sounds confident, even when acceptance criteria are untestable. Builders implement against ambiguity and produce plausible-but-wrong work.
- **Repeated mistakes**. No mechanism logs what went wrong and why, so the same class of error recurs across tasks.
- **Stale documentation**. Architecture docs, READMEs, and routing docs drift from reality. Builders read out-of-date context and propagate the drift.
- **Reviews that either rubber-stamp or loop forever**. Without explicit stopping rules and severity discipline, reviewers either approve too quickly or generate infinite new findings each pass.
- **Hidden systemic flaws**. Architectural or design-pattern problems cause recurring bugs, but neither Claude nor the user can see the pattern from inside any single session.
- **Drift without awareness**. Claude operates from an incorrect or myopic frame, produces work that locally passes checks, and neither party realizes the larger goal is no longer being served.
- **Tooling fragmentation**. Each project rebuilds the same scaffolding from scratch, with no path for insights to compound across projects (where the user wants them to).
- **Cross-repo signal bleed**. Users working across multiple repos in a single session muddy pattern-detection if findings can't be scoped properly.

-----

## Solution Overview

Five concurrent layers, all packaged as a single Claude Code plugin:

1. **Knowledge layer** — a typed graph of project state. Per-project SQLite DB for project-scoped data + optional shared meta-graph for cross-project patterns.
2. **Planning layer** — converts user intent into specs whose acceptance criteria are falsifiable, with declared scope. Refuses dispatch until criteria are verifiable.
3. **Build layer** — small agent teams (builder + spec-checker + code-reviewer + contrarian) operating in parallel where work is orthogonal, serial where surfaces overlap. Coordinated by an orchestrator that computes the dependency DAG.
4. **Review layer** — per-PR pipeline with severity-gated stopping rules. Full review re-runs every round; severity discipline drives convergence. Separate periodic architectural-review pass on its own cadence.
5. **Meta layer** — pattern detection, drift audits, calibration tracking, postmortem-driven learning. Reads from both per-project graph and (if opted-in) cross-project meta-graph.

Every layer reads from and writes to the graph via the plugin's MCP server. Every "done" claim is verified by a context that did not produce the work. Every finding is a typed node, never session-bound memory.

-----

## Locked Gating Decisions

These five decisions shape everything downstream. All ratified.

### Gating-1: Graph substrate

**SQLite + `sqlite-vec` extension.**

Single file per database, transactional integrity, vector search in-store via extension, zero infrastructure, easy inspection. Migration path to Postgres or graph DB exists if volume justifies later. Two databases:

- Per-project: `./.agentic/graph.db`
- Optional cross-project meta (if user opts in): `~/.agentic/meta.db` or a workspace-level path

### Gating-2: Tool interface

**Local stdio MCP server, bundled in the plugin.**

The server runs as a child process spawned by Claude Code, communicating over stdio. Zero hosting cost. No network dependency. Fully compatible with Claude Max subscription. Single tool surface shared across all subagents. Typed JSON schemas for parameters. The plugin's `.mcp.json` registers the server automatically on install.

### Gating-3: State model

**Single source of truth via tool-mediated enforcement, with session-start prompt injection for context.**

Agents have no durable state outside the graph. The only path to persistence is tool calls — `log_finding`, `mark_criterion_satisfied`, `record_decision`, `flag_blocker`, etc. There is no "save my work" surface beyond these tools.

Token cost is controlled by **targeted reads, not bulk loads**:

- Specs carry a `required_reads` field listing only the nodes the agent needs
- Heavy nodes carry summary fields for first-pass reads
- Subagents receive narrower slices than the main agent
- The MCP server exposes small parameterized queries

Enforcement, in order of strength:

- **Primary**: tool-mediated durability (no other path exists)
- **Secondary**: task-completion verification — `mark_spec_satisfied` runs gates before accepting
- **Tertiary**: Claude Code SessionEnd hook as observability backstop (not enforcement)

### Gating-4: Codebase target

**Bootstrap-first, with dogfooding as an explicit engineering philosophy that propagates to all artifacts the system builds.**

Phase 0 is built manually with Claude Code unaided. From Phase 1 onward, the system uses itself to build itself.

Dogfooding is the special case (builder = user) of a broader principle: **every artifact built by this system has an observable feedback loop with reality**. When builder != user, the loop takes a different form (telemetry, user feedback, override-pattern detection, test suite). Bypasses are bugs in the system, tracked as `SystemUsabilityBug` findings.

### Gating-5: Packaging

**Single Claude Code plugin, fully self-contained, no cross-plugin runtime dependencies.**

Distributed via git repo (`/plugin install github:user/agentic-engineering`) or marketplace later. Components map directly to plugin slots:

- Subagents -> `agents/`
- Skills (router, spec-writing, reviewing, pattern-detection, architectural-review) -> `skills/`
- SessionStart hook + others -> `hooks/hooks.json`
- Graph MCP server -> `.mcp.json` + bundled server code
- Slash commands (`/agentic:init`, `/agentic:new-spec`, `/agentic:dispatch`, `/agentic:review-pr`, `/agentic:find-patterns`, `/agentic:import-spec`) -> `commands/`

**Project boundary via git-style walk-up resolution.** SessionStart hook walks up from cwd looking for `.agentic/`; the closest one wins. If none found, system is inactive. The user controls boundary placement by where they run `init`. SessionStart hook displays the active project path on activation so the user always knows which `.agentic/` is in use.

**Two-tier state model (opt-in)**:

- Per-project state in `./.agentic/` in each project root (always)
- Cross-project meta-state in `~/.agentic/meta.db` or a workspace-level shared DB (only if user explicitly opts in via scope mode)

**Activation strategy**: install plugin globally. The SessionStart hook is inert if no `.agentic/` exists in cwd or any ancestor. Unrelated projects pay only the tiny always-on cost of skill/agent descriptions.

**No CLAUDE.md anywhere** — neither user's nor project's. Static philosophy lives in `skills/router/SKILL.md` and related plugin skill files. Dynamic per-session context flows through the SessionStart hook injection, phrased as factual project information per Claude Code's prompt-injection defense behavior.

**Tactical practices embedded in our own subagent prompts** (not references to other plugins). TDD, systematic debugging, security audit, intent-clarification — each is opinionated guidance inside the relevant subagent's prompt, concise (a few sentences, not skill-file-length). Phase 0 ships minimal versions; Phase 1+ refines.

**Plugin compatibility approach**: we never disable other plugins' components. The conflict-detection walkthrough is informational — names overlaps, notes that both can coexist via namespacing, points the user at `/agentic:import-spec` if they want to bridge external planning output into our graph. The user disables their other plugins themselves if they want to, via Claude Code's native `/plugin disable`.

-----

## Core Mechanics

### 1. The Knowledge Graph

A typed graph held across sessions in one or two SQLite databases (depending on scope mode).

**Entity types** (minimum):

| Entity               | Purpose                                                                          |
|----------------------|----------------------------------------------------------------------------------|
| `Goal`               | Top-level user intent                                                            |
| `Epic`               | Major workstream                                                                 |
| `Task` / `Subtask`   | Buildable units with specs                                                       |
| `Spec`               | Acceptance criteria for a task; carries scope field                              |
| `Decision`           | A locked choice with rationale                                                   |
| `Bug`                | A defect, open or resolved                                                       |
| `Finding`            | Anything a reviewer or agent noticed; inherits scope from parent                 |
| `Pattern`            | A systemic observation across many findings (cross-project if scope mode allows) |
| `Module`             | A logical unit of the codebase                                                   |
| `File`               | A code artifact                                                                  |
| `Review`             | A review event with verdict                                                      |
| `Retro`              | Postmortem of a mistake or surprise; tagged by failed layer                      |
| `ArchDebt`           | Architectural debt item                                                          |
| `SystemUsabilityBug` | Finding subtype for bypasses of our own system                                   |

**Relation types** (minimum):
`implements`, `depends-on`, `blocks`, `supersedes`, `caused-by`, `observed-in`, `touches`, `references`, `derived-from`.

**Required fields on every node**: id, type, status, severity, owner, created-at, last-touched, body, summary (for heavy nodes), tags, **scope** (auto-inherited or auto-inferred).

**Three indexing modes**:

- Hierarchical (Goal -> Epic -> Task -> Subtask)
- Embedding-based via sqlite-vec (similarity queries)
- Tag-based (severity, area, age, status, **scope**)

**Scope semantics**:

- Soft tag, not a hard dispatch gate. Tasks dispatch even with fuzzy scope.
- Used by pattern-finder for correlation boundaries. High-confidence patterns within a clear scope; conservative cross-scope correlation.
- Auto-inferred from: file paths mentioned in node body, files the agent has touched in the session, parent node's scope, cwd at creation. User can override; auto-inferred is the default.

**Anti-rot enforcement**: open nodes untouched in N days surface for triage. The orchestrator's job includes weeding; no other agent does this.

**Cross-project boundary**: project-scoped data always stays in `./.agentic/graph.db`. `Pattern` nodes and reviewer calibration data flow to the meta-graph only if scope mode is `workspace` or `personal`. Default `isolated` keeps everything local.

### 2. Ground-Truth Anchoring

Verification anchors:

- Executable tests, deterministic pass/fail
- Type checks, linters, static analysis
- Reproducibility (fresh agent + only the spec produces an equivalent artifact)
- Runtime telemetry where applicable
- The user, sparingly, as final arbiter

Taste-based judgments surface candidates; they never gate.

### 3. Planning Layer

A `Spec` cannot dispatch until every acceptance criterion has a verification mechanism. The orchestrator refuses unready specs.

**Spec template fields**:

- Goal it serves
- **Scope** (auto-inferred, user-overridable): which repos/modules/files
- Boundaries (in/out)
- Acceptance criteria, each with verification mechanism
- Dependencies
- Estimated complexity
- Known risks / open questions
- Required reads (graph slice + relevant skill/module docs)
- **Feedback loop**: how will we know if the resulting artifact is working correctly in real use? What's the path from misbehavior back to a fix?

Both `feedback loop` and `acceptance criteria verification` are hard gates. Specs without answers don't dispatch.

**Intent clarification** is embedded in the spec-writer subagent prompt as a Socratic question pass before locking the spec. Native to our plugin; does not depend on any external plugin's brainstorming skill.

### 4. Build Teams (Atomic Unit)

| Role              | Input                                  | Output                       | Failure mode guarded against    |
|-------------------|----------------------------------------|------------------------------|---------------------------------|
| **Builder**       | Spec, required reads                   | Implementation + evidence    | —                               |
| **Spec-checker**  | Spec + artifact (not builder's prose)  | Pass/fail per criterion      | Builder rationalizes "done"     |
| **Code-reviewer** | Artifact + module conventions          | Findings by severity         | Implementation works but is bad |
| **Contrarian**    | Artifact + spec                        | Reasons this might be wrong  | Reviewer consensus collapse     |

Context isolation between roles is what makes the team work. The spec-checker never sees the builder's justifications. The contrarian is explicitly tasked to find reasons the work is wrong, not to confirm it's right.

**Embedded tactical practices in the builder prompt**:

- Test-first when spec requires it: write failing tests, verify they fail without new code, implement, verify they pass. Tests count as evidence.
- Systematic debugging when investigating a bug: reproduce -> isolate -> identify root cause -> fix -> verify. Log root cause to a `Retro` node tagged `caused-by`.

**Embedded tactical practices in the code-reviewer prompt**:

- Security/audit checks for known vulnerability classes appropriate to the language/framework.
- Adherence to module-level conventions read from the relevant skill file.

All tactical guidance is concise (a few sentences per practice), embedded in the relevant subagent prompt, no references to other plugins.

### 5. Parallelism via Orchestrator

The orchestrator implements nothing. It:

- Computes the dependency DAG from the graph
- Identifies orthogonal work
- Schedules parallel teams in isolated git worktrees
- Forces serial when surfaces overlap
- Weeds stale graph nodes
- Surfaces escalations to the user

### 6. Per-PR Review Pipeline

**Severity tiers**:

| Severity                | Definition                                                                                              | Action                                                                                                                                                                                              |
|-------------------------|---------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Critical / Blocking** | Correctness violation, security issue, breaking change to public surface, missing acceptance criterion  | Loop until resolved. No hard cap.                                                                                                                                                                   |
| **Important**           | Real problem, not a ship-blocker                                                                        | Reviewer flags with "fix-in-PR vs backlog" recommendation. Orchestrator (or user) decides. If "fix-in-PR" -> treated as critical for this round. If "backlog" -> logged as `Finding`, not blocking. |
| **Suggested**           | Style, minor refactor, micro-optimization                                                               | Logged, feeds pattern-finder. Not actioned per-PR.                                                                                                                                                  |
| **Strengths**           | What the work did well                                                                                  | Logged for reviewer calibration.                                                                                                                                                                    |

**Loop behavior**:

Every round, the **full** PR review fires (spec-checker + code-reviewer + contrarian, all of them). Findings classified by severity. Criticals (and importants triaged as fix-in-PR) block. Other importants and suggesteds land in the backlog as graph nodes linked to the PR.

**Critical-loop persistence**:

- Criticals loop until resolved. No iteration cap.
- After 3 iterations on the same critical (same root cause), surface a **non-blocking diagnostic** to the user with hypotheses ("spec may be wrong, not implementation", "approach may be architecturally unsuitable"). Optionally trigger architectural sub-review. **The loop continues**; the system asks for help instead of stopping.
- Each iteration's findings feed the pattern-finder. Stubborn criticals become learning data via `Retro` nodes tagged by failed layer.

**Stopping rules**:

- **Diminishing returns**: pass N+1 finds fewer criticals than N AND no regressions of N's approvals -> at floor, merge.
- **Stability check**: pass N+1 finds criticals that N should have caught -> reviewer is unstable, log as `Pattern`, distrust this reviewer until investigated.

**Importants triage in-loop**: every important comes with a reviewer recommendation. The orchestrator has a default policy (fix-in-PR if recommended; else backlog) and the user can override. This is the difference between triaging and ignoring.

### 7. Periodic Architectural Review

A separate machine with separate incentive structure. Cadence-driven, not PR-driven.

**Inputs**: codebase tree, architectural docs, recent `Pattern` nodes, bug history, `Retro` nodes, recurring `Finding` clusters.

**Question**: are there shapes in this code causing recurring problems? Modules everyone is afraid to touch? Leaked abstractions? Misplaced test coverage? Bugs clustering at a boundary?

**Output**: `ArchDebt` nodes linked to concrete evidence. These become Epic-level items competing with feature work.

**Incentive isolation**: this reviewer has no PR to ship. Its only output is observations about shape.

**Cadence**: weekly, every N PRs, before milestone gates. Exact thresholds tunable.

**Special question for shipped artifacts**: does this artifact have an observable feedback loop, or does it ship blind? Blind artifacts get tagged `ArchDebt`, not blocked. Conscious debt instead of invisible debt.

### 8. Pattern Detection (Bottom-Up)

Scheduled scan over recent `Finding`, `Bug`, `Retro` nodes. Looks for clusters by module, category, reviewer, time-of-day, spec-author, scope, etc. Produces `Pattern` nodes the user reads.

**Within-scope correlation** is the default mode: patterns that emerge inside one scope (e.g., one repo) are high-confidence.

**Cross-scope correlation** runs only if scope mode allows and only with a high robustness bar — patterns that appear across multiple scopes are interesting precisely because they're cross-cutting.

Examples:

- Within-scope: "Five bugs in last month all touched repo-a's auth module"
- Cross-scope (workspace mode): "You under-spec error handling in every repo you touch in this workspace"
- Cross-project (personal mode): "Specs written in sessions under 30 minutes are rejected at 2x the rate across all your projects"

### 9. Self-Knowledge & Drift Detection

- **Pre-commitment to falsifiable claims** at every layer
- **Out-of-band re-derivation**: reviewers see only spec + artifact
- **Postmortem-everything**: every error/blocker/retracted decision produces a `Retro` node tagged with which layer failed (spec / implementation / review / unknowable)
- **Confidence calibration tracking**: discount future confidence from roles whose high-confidence claims were wrong
- **Periodic alignment check**: scheduled prompt comparing original `Goal` to current state — does this look like progress?
- **Contrarian role** at build-team level + meta-level for self-audit
- **Subagent prompts reflect the ceiling philosophy**: agents told they have access to memory and patterns no individual would have, expected to reason with that confidence. Not framed as junior.

### 10. Codebase Routing

The codebase is an actor. Agents read its affordances before acting.

- **Skill files** in the plugin (`skills/router/SKILL.md` is the entry point) hold static project conventions and routing rules
- **Architectural map** maintained as a `Module` subgraph in the project graph; kept fresh via tripwire
- **Symbol index** maintained for fast jump-to-definition by agents
- **Builder workflow forces** reading the relevant module's skill file as first step

### 11. Plugin Compatibility

**Self-containment principle**: our plugin makes no runtime references to any other plugin's skills, agents, or commands. Tactical practices (TDD, debugging, audit, intent-clarification) are embedded in our own subagent prompts. Our plugin works fully whether other plugins are installed or not.

**At init**, `/agentic:detect-conflicts` (also runs as part of `/agentic:init`):

1. Lists installed plugins by inspecting `~/.claude/plugins/` and parsing manifests
2. For known overlaps (v1: Superpowers only — others are listed as "unknown, review yourself"), surfaces informationally:

   ```
   Detected: superpowers (installed, enabled)

   Overlapping skill categories: planning, code-review, TDD, debugging, audit, brainstorming.

   Both plugins can coexist via Claude Code's namespacing. Our cycle uses
   embedded tactical guidance, integrated with our graph.

   Options:
     - Use ours end-to-end (recommended): full graph integration. To avoid
       double-firing on PRs, consider /plugin disable superpowers.
     - Use Superpowers for ad-hoc work, ours for tracked tasks: both stay
       enabled, just be aware of doubled token cost on overlapping triggers.
     - Use Superpowers' planning, ours for build/review: use
       /agentic:import-spec to bring their plan output into our graph as a
       falsifiability-validated Spec node.

   No automatic changes will be made. You decide.
   ```

3. Records the user's stated preference in `./.agentic/compatibility.json` for future sessions

**Bridge command**: `/agentic:import-spec` — for users who insist on producing plans outside our system, this takes text input or points at a file and runs it through our falsifiability validator, producing a proper Spec node if it passes, rejecting with reasons if not.

**Critical constraints**:

- We never disable other plugins' components. Ever.
- We never reach into other plugins' files or settings.
- If the user wants to disable another plugin, they do it themselves via `/plugin disable`.
- We can disable our own components if the user prefers another plugin's version, but we recommend against it (graph fragmentation).

-----

## Design Decisions (Ratified)

All ratified as Phase 0 defaults. The meta layer (Phase 4) tunes them empirically.

| #    | Decision                                                                                                                  | Rationale                                                                                                                                       |
|------|---------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| D-01 | Knowledge as a typed graph (SQLite + sqlite-vec), not folders of markdown                                                 | Folders rot. Graphs enforce typed relations + enable pattern detection.                                                                         |
| D-02 | Every "done" claim verified by an independent context                                                                     | Self-grading agents converge to whatever the prompt rewards.                                                                                    |
| D-03 | Specs cannot dispatch until acceptance criteria are falsifiable                                                           | "Done" undefined is the deepest planning failure.                                                                                               |
| D-04 | Specs include a "feedback loop" field                                                                                     | Propagates ground-truth anchoring to artifacts the system builds.                                                                               |
| D-05 | Build teams of 4 roles (builder + spec-checker + code-reviewer + contrarian)                                              | Team converges before handoff. Solo builders are brittle.                                                                                       |
| D-06 | Contrarian role explicitly tasked to find what's wrong                                                                    | Without asymmetric prompts, reviewers agree with builders.                                                                                      |
| D-07 | Four-tier severity: Critical / Important / Suggested / Strengths                                                          | Blocks ship / fills backlog / feeds pattern-finder / calibrates reviewers.                                                                      |
| D-08 | Criticals loop until resolved, no hard iteration cap                                                                      | Giving up after N tries papers over real bugs.                                                                                                  |
| D-09 | After 3 iterations on same critical, non-blocking diagnostic to user; loop continues                                      | Avoids silent spin without interrupting flow.                                                                                                   |
| D-10 | Importants triaged in-loop with reviewer "fix-in-PR vs backlog" recommendation                                            | Triage, don't ignore; in-loop, don't defer indefinitely.                                                                                        |
| D-11 | **Full PR review re-runs every round**, severity discipline drives stopping rules                                         | Re-running full review with severity tiers converges via discipline, not scope narrowing. (Replaces previous "never re-run broad review" rule.) |
| D-12 | Architectural review on a cadence, not per PR                                                                             | PR reviewers want to ship. Architectural needs incentive isolation.                                                                             |
| D-13 | Pattern-finder runs as scheduled job, not in-line                                                                         | In-line biases toward current task. Scheduled sees distribution.                                                                                |
| D-14 | Orchestrator does not implement anything                                                                                  | Mixing implementation collapses scheduling judgment.                                                                                            |
| D-15 | Parallel where orthogonal, serial where surfaces overlap                                                                  | Integration is the bottleneck. DAG enforces.                                                                                                    |
| D-16 | Postmortem-tag every error by failed layer                                                                                | Tag distribution is the system's diagnostic.                                                                                                    |
| D-17 | Periodic alignment check against original Goal                                                                            | Catches drift into local optima.                                                                                                                |
| D-18 | Every artifact has an observable feedback loop with reality                                                               | Ground-truth anchoring extended to shipped artifacts.                                                                                           |
| D-19 | Bypassing the system is tracked as `SystemUsabilityBug`                                                                   | Bypass impulse is the signal of what to fix.                                                                                                    |
| D-20 | All system files in plugin + `.agentic/` namespace. Never touch any CLAUDE.md.                                            | Avoids collision with user's files and other systems.                                                                                           |
| D-21 | SessionStart hook injects router-style tutorial pointing to plugin skills + current graph state                           | Stronger context weighting than CLAUDE.md. Dynamic per session.                                                                                 |
| D-22 | Hook injection phrased as factual project info, not imperative commands                                                   | Prevents triggering Claude Code's prompt-injection defenses.                                                                                    |
| D-23 | Project boundary resolved via git-style walk-up from cwd for `.agentic/`                                                  | Standard, predictable, user-controlled by where they run init.                                                                                  |
| D-24 | SessionStart hook displays which `.agentic/` is active on every activation                                                | User always knows which project context they're in.                                                                                             |
| D-25 | Specs include a `scope` field; findings/bugs/decisions auto-inherit or auto-infer scope                                   | Prevents cross-repo signal bleed without manual overhead.                                                                                       |
| D-26 | Scope is a soft tag for pattern-finder correlation, not a hard dispatch gate                                              | Doesn't add friction; just guides downstream correlation.                                                                                       |
| D-27 | Three scope modes: `isolated` (default), `workspace`, `personal`. Configured per project.                                 | Cross-project sharing is opt-in, not automatic.                                                                                                 |
| D-28 | Plugin is fully self-contained — no cross-plugin runtime references in subagent prompts                                   | Plugins should be distributable units; cross-plugin deps are an anti-pattern.                                                                   |
| D-29 | Tactical practices (TDD, debugging, audit, intent-clarification) embedded as concise guidance in our own subagent prompts | Self-contained, no external dependencies; Phase 0 minimal, Phase 1+ refined.                                                                    |
| D-30 | We never disable other plugins' components                                                                                | We don't have authority to modify another plugin's internal state.                                                                              |
| D-31 | Conflict detection at init is informational only; user decides what to disable                                            | Respects user choice; avoids reaching into others' plugins.                                                                                     |
| D-32 | `/agentic:import-spec` is the only bridge — for ingesting external plans into our graph                                   | Users who insist on external planning have a path; default is our planning.                                                                     |
| D-33 | v1 known-overlap registry contains Superpowers only; other plugins surface as "unknown"                                   | Don't pretend to know about plugins we haven't tested against.                                                                                  |
| D-34 | Subagent prompts framed as having graph-backed memory and patterns no individual would have                               | Aligns prompt framing with system's actual capability ceiling.                                                                                  |
| D-35 | System aspires to exceed individual engineers on memory-compounded dimensions; complements on novel reasoning             | Don't preemptively limit the ceiling.                                                                                                           |

-----

## Open Questions

Genuinely undecided. Spec writer or empirical tuning will resolve.

1. **Architectural-review cadence**: weekly? Every N PRs? Before milestones only? All three? Tune per project.
2. **User-in-the-loop escalation UX**: when the system surfaces a stuck critical diagnostic, how is it shown? CLI prompt, file, dashboard?
3. **Token / cost budget per task and per session**: at what cost does the scaffolding stop being worth it? Need a tripwire metric.
4. **Integration with existing external tools** (GitHub Issues / Linear / Notion / Jira): graph mirrors to one, or stays standalone? If mirroring, who is source of truth?
5. **Existing project bootstrap**: greenfield is simple; brownfield needs a graph-backfill procedure. What's the minimum useful backfill?
6. **Reviewer model selection**: same model for builder and reviewer (cheap, correlated failures) or different models / temperatures? Decide empirically.
7. **First bootstrap task**: what small problem does Phase 0 build itself with, end-to-end, to validate the foundation works?
8. **Rollback trigger**: if issues-found-per-PR doesn't improve over N PRs vs. a baseline, what's the protocol for stripping back scaffolding?
9. **Workspace-bleed empirical behavior**: does auto-inferred scope + soft tagging actually prevent signal mixing in real cross-repo workflows? Observe post-Phase-0, tune if needed.
10. **Subagent prompt bloat**: with tactical practices embedded, do prompts stay focused or balloon past effective attention range? Measure in Phase 0, refactor to discoverable skill files if needed.
11. **Tactical practice polish**: our embedded TDD/debugging/audit guidance starts minimal in Phase 0. What's the path to refining each — `Retro` analysis driving improvements? User feedback? Empirical comparison against specialist plugins?
12. **Conflict detection beyond Superpowers**: which plugins go in the v1 known-overlaps registry over time? Empirical, fill in as the ecosystem matures.
13. **SessionStart hook robustness**: verify hook injection works reliably on target Claude Code version; document any workarounds.

-----

## Success Metrics

| Metric                          | Target                                                                                              | Maps to                        |
|---------------------------------|-----------------------------------------------------------------------------------------------------|--------------------------------|
| Information retention           | >95% of session findings/follow-ups exist as graph nodes one week later                             | Information loss               |
| Spec falsifiability             | 100% of dispatched specs have verification mechanisms (gating rule)                                 | Plans look complete but aren't |
| Repeat-error rate               | Trending toward zero: # of `Retro`s whose `caused-by` matches a prior `Pattern`                     | Repeated mistakes              |
| Doc freshness                   | Median age of architectural map updates < K days after relevant decisions                           | Stale documentation            |
| Review loop convergence         | Median <= 2 iterations to resolve criticals; diagnostic-fire rate < 10%                             | Infinite review loops          |
| Systemic issue detection lag    | First `Pattern` named within N findings of the class                                                | Hidden systemic flaws          |
| Drift detection                 | High agreement rate when system flags drift and user agrees it's real                               | Drift without awareness        |
| Reviewer calibration            | Strengths-to-issues ratio per reviewer stays in healthy range; outliers flagged                     | Reviewer mode collapse         |
| Token efficiency                | Tokens per resolved Critical and per shipped PR trend down as graph matures                         | Cost runaway                   |
| `SystemUsabilityBug` rate       | Trending down over time                                                                             | Dogfooding signal preservation |
| Cross-project insight rate      | Number of `Pattern` nodes in meta-graph that produce actionable user changes (if scope mode allows) | Tooling fragmentation          |
| Scope-bleed signal              | Pattern-finder's cross-scope correlation false-positive rate (does it surface noise as patterns?)   | Cross-repo signal bleed        |
| Subagent prompt size            | Avg tokens per subagent system prompt stays within attention-effective range                        | Prompt bloat                   |

-----

## Phased Rollout

Each phase has a verifiable exit gate. Do not start phase N+1 until phase N's gate is met.

### Phase 0: Foundations (MVP)

**Goal**: graph that doesn't rot + falsifiable specs + independent verification + walk-up project resolution + minimal embedded tactical guidance.

**Build**:

- Plugin scaffold (`plugin.json`, directory structure)
- Graph schema (entity types + relations + indexes + scope field) in SQLite + sqlite-vec
- MCP server with minimal tool set: `create_node`, `update_node`, `link_nodes`, `query_graph`, `log_finding`, `mark_criterion_satisfied`
- `Spec` template with falsifiability + feedback-loop validation + scope field with auto-inference
- SessionStart hook script: walks up looking for `.agentic/`, displays which one is active, injects router context if found, inert if not
- `skills/router/SKILL.md` describing the system and pointing to other skills
- Two-role flow (builder + spec-checker), no parallelism yet
- `/agentic:init` command that scaffolds `.agentic/`, asks for scope mode, creates config
- `/agentic:detect-conflicts` command — informational only
- `/agentic:import-spec` command — bridge for external plans
- **Minimal** tactical guidance embedded in subagent prompts (a few sentences each for TDD, debugging, intent-clarification). Refinement is Phase 1+.

**Exit gate**: A task can be dispatched, built, spec-checked, and result in a `Finding` node logged to the graph. Graph survives session restarts. Spec dispatch is blocked if criteria are not falsifiable or feedback loop is missing. Plugin installs cleanly via `/plugin install`. Walk-up resolution finds project correctly across at least three test scenarios (nested, workspace-level, no-project). Hook injection verified on target Claude Code version. Conflict detection runs without modifying any other plugin.

### Phase 1: Build Pipeline

**Goal**: full four-role team + four-tier severity review + critical-loop behavior + refined tactical practices.

**Build**:

- Code-reviewer and contrarian roles
- Severity gating with four buckets
- Full-PR-review-each-round loop with critical persistence and 3-iteration non-blocking diagnostic
- Importants triage with reviewer fix-in-PR-vs-backlog recommendation
- Diminishing-returns and stability stopping rules
- Postmortem tagging by failed layer
- `/agentic:dispatch` and `/agentic:review-pr` commands
- Refined tactical practices in subagent prompts (TDD, debugging, code-review heuristics, contrarian patterns)

**Exit gate**: A PR cycles through the four-role team. Severity correctly applied. Criticals loop until resolved. Importants triaged in-loop with backlog landing where appropriate. Stopping rules fire correctly on convergence and instability. Postmortem layer tagging operational on at least one real `Retro`.

### Phase 2: Orchestration & Parallelism

**Goal**: multiple teams in flight, coordinated by the orchestrator.

**Build**:

- Orchestrator agent computing the dependency DAG
- Git worktree management for parallel teams
- Parallel-when-orthogonal scheduling, serial-when-shared enforcement
- Anti-rot weeding pass on the graph
- Stale-spec detection
- Confidence calibration tracking per role

**Exit gate**: Two teams can run in parallel on orthogonal tasks without merge collisions. Graph weeding runs on schedule. At least one confidence-calibration adjustment has fired.

### Phase 3: Meta-Review

**Goal**: pattern detection + periodic architectural review + drift checks + optional cross-project meta-graph.

**Build**:

- Scheduled pattern-finder over `Finding` / `Bug` / `Retro` nodes producing `Pattern` nodes (within-scope first; cross-scope if mode allows, with high robustness bar)
- Cross-project meta-graph (`~/.agentic/meta.db` or workspace path) populated only if scope mode is `workspace` or `personal`
- Architectural-review agent with cadence and incentive isolation
- Periodic alignment check against original `Goal`
- Architectural map tripwire
- `/agentic:find-patterns` command for on-demand pattern surfacing

**Exit gate**: At least one real `Pattern` and one real `ArchDebt` produced and triaged. Alignment check has run. If any user is in `workspace` or `personal` scope mode, meta-graph contains at least one cross-scope pattern.

### Phase 4: Hardening & Self-Improvement

**Goal**: the system reads its own mistakes and gets better.

**Build**:

- Full automated postmortem tagging
- Reviewer strengths-to-issues ratio monitoring with automatic miscalibration flagging
- Auto-tuned escalation thresholds based on observed convergence
- Integration with chosen external tools (per Open Questions)
- `SystemUsabilityBug` pattern detection feeding into prompt/template improvements
- Tactical-practice refinement loop: `Retro` data drives improvements to embedded TDD/debugging/audit guidance

**Exit gate**: A `Retro` analysis has produced a graph-visible improvement to a prompt, template, or threshold — the system has changed itself in response to its own data.

### Phase 5+: Steady State

Continuous tuning driven by the meta layer. The exit gate for "is the system built" is intentionally never met.

-----

## Failure Modes (Threat Model)

In rough order of likelihood:

1. **Spec under-specification**. *Mitigation*: orchestrator refuses unready specs. Feedback-loop field also gated.
2. **Reviewer mode collapse**. *Mitigation*: contrarian role at team level, varied prompts, strengths-to-issues ratio tracking.
3. **Graph rot**. *Mitigation*: task templates force graph reads; weeding is orchestrator's job, scheduled.
4. **Infinite review loops**. *Mitigation*: severity discipline (only criticals block), diminishing-returns stopping, stability check, 3-iteration non-blocking diagnostic.
5. **Coordination collapse under parallelism**. *Mitigation*: DAG + worktrees + serial-when-shared.
6. **Sycophantic acceptance**. *Mitigation*: contrarian role + user actively rewards disagreement.
7. **Scaffolding eats the project**. *Mitigation*: ruthlessly cut layers that don't pay for themselves. Phase boundaries are real.
8. **Cost runaway**. *Mitigation*: per-task token caps, budget tracking, automatic escalation on overrun. Plugin always-on cost minimized by concise descriptions.
9. **Integration drift with external tools**. *Mitigation*: pick one as source of truth; the other is a derived view.
10. **User trust collapse**: signal/noise drops below useful. *Mitigation*: aggressive de-noising; high bar for `Pattern` or `ArchDebt`.
11. **Dogfooding signal loss via bypass**. *Mitigation*: `SystemUsabilityBug` tracking.
12. **Plugin always-on cost growth**. *Mitigation*: monitor via `claude plugin show`; keep descriptions concise.
13. **Cross-project pattern pollution**. *Mitigation*: default scope is `isolated`; only `Pattern` nodes flow cross-scope; high robustness bar before cross-scope correlation surfaces.
14. **Cross-repo signal bleed within a workspace-mode project**. *Mitigation*: auto-inferred scope tags; pattern-finder respects scope boundaries; cross-scope correlation has higher bar than within-scope.
15. **Subagent prompt bloat from tactical practices**. *Mitigation*: keep embedded guidance concise; if prompts grow past attention-effective range, refactor to discoverable skill files our subagents read on demand.
16. **Tactical practices under-polished in early phases**. *Mitigation*: ship minimal in Phase 0, refine in Phase 1+; let `Retro` data drive improvements.
17. **Walk-up resolution finds wrong `.agentic/`**. *Mitigation*: SessionStart hook always displays which one is active; user can override or move boundary by re-running init.
18. **Auto-inferred scope frequently wrong**. *Mitigation*: scope is soft, user can override; pattern-finder is conservative on fuzzy scopes. Observe accuracy in Phase 0.
19. **Cross-plugin coexistence pain**. *Mitigation*: namespacing handles technical conflicts; informational conflict-detection at init surfaces overlaps; `/agentic:import-spec` provides escape hatch for external planning.

-----

## Notes for the Spec Writer

This PRD locks the shape. The spec writer's job is mechanical: convert ratified decisions into detailed specifications. Specifically:

- **Plugin manifest**: exact `plugin.json` fields, version strategy, metadata
- **Graph schema**: full SQLite DDL — table definitions, column types, indexes, foreign keys, migration ordering, scope-field semantics
- **MCP server tool surface**: exact function signatures, parameter schemas, return types, error semantics, for every tool agents call
- **Spec template**: full markdown structure with examples for (a) trivial task, (b) real feature, (c) bug fix. Include scope auto-inference logic.
- **Falsifiability validator**: rules deciding whether a criterion is verifiable enough to dispatch
- **Feedback-loop validator**: same, for the feedback-loop field
- **Scope inference logic**: heuristics for auto-inferring scope from spec body, parent nodes, cwd, recent file activity
- **Subagent definitions**: full system prompts for builder, spec-checker, code-reviewer, contrarian, orchestrator, architectural-reviewer, pattern-finder, spec-writer. Each includes embedded tactical guidance (concise, no cross-plugin references).
- **Skill files**: `router/SKILL.md` and one SKILL.md per workflow (spec-writing, reviewing, pattern-detection, architectural-review)
- **SessionStart hook**: full script handling walk-up resolution, presence/absence of `.agentic/`, dynamic context injection with current task state, phrased as factual project information. Always displays active project path.
- **Slash commands**: `/agentic:init` (with scope-mode selection), `/agentic:new-spec`, `/agentic:dispatch`, `/agentic:review-pr`, `/agentic:find-patterns`, `/agentic:detect-conflicts` (informational), `/agentic:import-spec` (bridge)
- **File layout**: exact directory structure inside the plugin and inside `.agentic/`
- **Conflict-detection logic**: read installed plugins from `~/.claude/plugins/`, check against the v1 known-overlap registry (Superpowers only), surface informationally, record user preference in `.agentic/compatibility.json`. Never modify other plugins' files.
- **First bootstrap task**: a small concrete problem that exercises the full Phase 0 flow end-to-end

**Implementation guidance for the build agent**:

- Build Phase 0 end-to-end before starting Phase 1. Resist scaffolding ahead.
- All ratified recommendations are Phase 0 defaults. The meta layer (Phase 4) tunes them empirically.
- Use git worktrees for parallel teams from day one of Phase 2.
- Every subagent's first action on any task: read the relevant graph slice + the relevant skill file. Encode this in every task template.
- The graph MCP server is the single tool surface for all durable state. No agent has any other write path.
- Hook output phrased as factual project information ("This project uses the agentic engineering system. Current task: X. Spec at `.agentic/specs/current.md`."), not imperative.
- Plugin always-on cost is a first-class concern — keep skill/agent/command descriptions concise.
- Subagent prompts include embedded tactical guidance (TDD, debugging, audit, intent-clarification). **No cross-plugin references in any subagent prompt.**
- Phase 0 tactical guidance is minimal (a few sentences each). Refinement is Phase 1+ work, driven by `Retro` data.
- Verify SessionStart hook injection works reliably on target Claude Code version before declaring Phase 0 complete.
- The walk-up resolution must be tested across at least these scenarios: nested project under workspace, workspace-level project, no project at all, multiple `.agentic/` at different levels (closest wins).
- `/agentic:detect-conflicts` never disables anything in other plugins. Only ours. And only with the user's explicit consent.

**Engineering philosophy** (for subagent prompts and meta-layer reasoning):

The system has access to memory and patterns no individual engineer could hold in their head — accumulated findings, decisions, retros, and patterns across all sessions and (if scope mode allows) all projects. Subagents should reason with that confidence. The aspiration is to exceed any individual engineer on dimensions that compound with memory and time (coverage, consistency, cross-time pattern detection, no-fatigue thoroughness, simultaneous multi-domain review) and to complement humans on novel reasoning where no prior pattern applies. Don't preemptively limit the ceiling; let real performance set it.

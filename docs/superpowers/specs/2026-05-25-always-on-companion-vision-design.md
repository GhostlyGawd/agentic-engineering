# Always-On Companion + Auto-Rehydrating Board: Vision Design

> **Type:** Strategic vision / architecture design doc (NOT an implementation plan).
> **Date:** 2026-05-25
> **Scope:** Four composing subsystems (R, H, PM-extensions, L, G) that turn the
> agentic-engineering system from a human-poked, single-session tool into an
> always-on companion with an auto-rehydrating, human-gated task board.
> **Status:** Design approved in brainstorming. Each subsystem gets its own
> spec -> plan -> implementation cycle later; this doc fixes the shape and the
> build sequence only.

---

## 0. Why this exists

Today the self-improvement machinery (pattern-finder, orchestrator, weeding,
calibration) only fires when a human types a command in a Claude Code session.
The PRD always assumed an *external cadence* would drive the stateless ticks, but
that external driver was never built. As a result:

- Scheduled scans do not actually run on a schedule.
- A learning signal (a `Pattern`, `Retro`, or `ArchDebt`) is surfaced but a human
  must manually act on it.
- There is no companion surface to watch the system work across projects.

This vision builds the missing external driver (R), a companion HUD (H), an
auto-rehydration loop that converts signals into planned work (L), and a human
approval gate that keeps autonomy safe (G). The PM/board responsibilities are
extended (Section 4) rather than reinvented.

### Locked decisions (from brainstorming)

1. **Runtime model = true 24/7 background service.** A persistent process that
   survives reboot, fires cadenced ticks on its own, and serves the HUD. Kept
   alive by the OS scheduler.
2. **Approval gate = auto-plan, gate before build.** Signals auto-create tasks
   and are planned unattended; the finished plan parks at a human approval gate.
   Planning runs while the user is away; building never does.
3. **HUD = master aggregate** across all registered projects, with the
   per-project workspace as the first-class, canonical surface. The master
   overview is additive and skippable.
4. **Cross-project meta-graph (sub-project C) = deferred**, with a clean seam so
   it can attach later without reworking the HUD.

### One framing that makes this smaller than it looks

The existing ticks (`orchestrate.tick`, `find_patterns_tick`, weeding) are
already stateless, never-raise, and touch only the graph. The always-on layer is
not a rewrite -- it is the external cadence the architecture already assumed.
The graph (`graph.db`) is already the single source of truth and the IPC layer:
ticks write, the HUD reads. "24/7 service" does NOT mean an always-running LLM --
the daemon is a cheap heartbeat + scheduler + state server, and the heavy agent
work is still spawned as headless `claude -p` runs (existing `headless.py`).

---

## 1. System architecture and topology

One new always-on process (the supervisor) plus one new read/control surface
(the HUD), wired around the existing graph.

```
                          +---------------------------------------------+
  Windows Task Scheduler  |  SUPERVISOR DAEMON  (always-on, cheap)       |
  (keep-alive / restart)  |  - reads ~/.agentic/registry.json            |
       starts ----------> |  - per-project cadence timers                |
                          |  - on tick: spawn headless claude work       |
                          |  - 127.0.0.1 control API (run-now/approve/..) |
                          |  - heartbeat + health in ~/.agentic/super.db  |
                          +------+----------------------------+----------+
                                 | spawns ticks               | control API
                                 v (existing, unchanged)      | (loopback)
  +------------------------------------------------+          |
  | per project:  ./.agentic/graph.db   (SoT)      | <--------+ HUD writes go
  |  orchestrate.tick / find_patterns_tick /       |          | through the
  |  arch-review tick / weeding / promotion tick   |          | daemon (audit)
  +-----------------+------------------------------+          |
                    | reads graph.db directly (display)       |
        +-----------+-----------------------------------------+
        |  HUD  (overview across registry  +  project view)   |
        +-----------------------------------------------------+
```

### Three communication paths

1. **Supervisor -> ticks.** The daemon is only a scheduler. On cadence it spawns
   the existing stateless ticks as headless work against a project's `graph.db`.
   Tick logic is untouched.
2. **HUD -> graph (read).** The HUD reads each project's `graph.db` directly to
   render boards, signals, and the approval queue. No protocol; leverages the
   existing source of truth.
3. **HUD -> supervisor (control).** Actions that need a *process* (run-now,
   pause-project, restart a tick) go over a loopback API. Actions that are state
   changes (Approve/Decline/Retry) are graph writes, proxied through the daemon
   so there is one audit path.

### What is genuinely new (everything else already exists)

- `~/.agentic/registry.json` -- project registry (paths, cadences, scope mode,
  enabled/paused).
- `~/.agentic/supervisor.db` (or a heartbeat file) -- EPHEMERAL runtime state
  only (last-run, PIDs, health). Never durable project data.
- The supervisor process + its loopback control API.
- The HUD app.
- A **promotion tick** (L) and an `awaiting_approval` task status + transitions
  (G) -- small additions to existing graph/PM logic.
- **`PRAGMA busy_timeout` in `db.connect` becomes mandatory** (was the optional
  tracked follow-up): the daemon's tick connections and the HUD's read
  connections now hit `graph.db` concurrently by design.

### Load-bearing invariant

Durable truth lives ONLY in per-project `graph.db`. The registry and
supervisor.db hold nothing worth mourning if deleted -- rebuildable from a disk
scan + graph state. A daemon crash loses zero work.

---

## 2. R -- the supervisor daemon

One process, deliberately dumb: a scheduler + health server with **no LLM and no
graph-business-logic** of its own. Everything it does is "spawn an existing tick"
or "answer a control request." Keeping it logic-free is what makes it safe to run
24/7 and trivial to restart.

### The registry (`~/.agentic/registry.json`)

```json
{
  "projects": [
    { "path": "D:/GitHub Projects/Studies/Superpowers Study",
      "enabled": true,
      "scope_mode": "isolated",
      "cadences": { "orchestrate": "2m", "pattern_finder": "6h",
                    "arch_review": "weekly", "weeding": "1d",
                    "promotion": "30m" },
      "promotion_cap": 5 }
  ]
}
```

A project is registered by `/agentic:init` (or a `register` control call).
Walk-up resolution still defines *what* a project is; the registry lists which
projects the daemon watches. Cadences are per-project.

### The loop (per project, per cadence)

```
for each enabled project:
  for each tick due (last_run + cadence <= now):
    spawn headless run of that tick against project/.agentic/graph.db
    record start in supervisor.db; on exit record end + outcome
```

Ticks run as **separate short-lived processes** (existing `headless.py` /
`--once` CLIs), not inside the daemon, each with a timeout. A hung or crashing
tick cannot take the daemon down. The daemon treats any tick failure as a logged
outcome, never its own crash -- mirroring the never-raise contract.

### State -- strictly ephemeral

`~/.agentic/supervisor.db` holds only per-project/per-tick `last_run`,
`last_outcome`, running PIDs, and a daemon heartbeat. Delete it and the daemon
rebuilds it (worst case: one tick fires early). Zero durable project data.

### Keep-alive on Windows

Registered once with Task Scheduler: start-at-logon + restart-on-failure + a
periodic "ensure-running" trigger (e.g., every 5 min, no-op if up). The OS
guarantees liveness while the daemon provides the rich live process. (systemd
unit / launchd agent are the equivalents on other platforms; Windows is target.)

### Control API -- loopback only (`127.0.0.1`)

| Endpoint | Purpose |
|---|---|
| `GET /health`, `GET /projects` | overview polling |
| `POST /projects/{id}/run/{tick}` | run-now (the clickable kick) |
| `POST /projects/{id}/pause` / `resume` | toggle a project's cadences |
| `POST /tasks/{id}/approve` \| `decline` \| `retry` | gate actions (proxied to a graph write) |
| `POST /register` / `POST /deregister` | add/remove a project |

### Failure and observability

Every tick spawn writes an outcome row. Consecutive failures of the same tick on
the same project raise a daemon-level health flag the HUD surfaces -- distinct
from in-graph CriticalLoop escalations (which concern *work*, not
*infrastructure*). Logs to `~/.agentic/logs/` with rotation. A crashed daemon is
restarted by Task Scheduler within the ensure-running interval; because all real
state is in the graphs, it resumes cleanly.

### What R explicitly does NOT do

Decide what work exists, decompose anything, judge quality, or hold opinions
about the board. Those are PM/planner/reviewer concerns. R answers only "is it
time?" and "go run that."

---

## 3. H -- the HUD

Two levels, one shared workspace component. The master overview is additive and
skippable; the per-project workspace is canonical.

### Level 1 -- Overview (the only cross-project screen)

```
+- agentic - overview --------------------- daemon healthy - 3 projects -+
|  PROJECT              ticks         gated   escalations   last activity |
|  Superpowers Study    ooooo ok       2 (!)      0          1m ago       |
|  retail-workflow      oooOo 1 stale  0          1 (!)       4h ago       |
|  solo-os              paused         0          0          --           |
|  [enter]=open  [r]=run-now  [space]=pause/resume  [a]=add project       |
+-----------------------------------------------------------------------=-+
```

Fans out across the registry, reading each project's own `graph.db` for counts +
the daemon's `/health`,`/projects` for tick status. Pure dashboard; opening it is
optional and lossless.

### Level 2 -- Project workspace (where the user lives)

```
+- Superpowers Study - isolated --------------------- [esc]=overview -+
| TICKS  orchestrate ok2m  pattern ok5h  arch run  weeding ok1d  [r]un |
+- BOARD ------------------------------[ Goals|Epics|Tasks|Subtasks ]-+
|  Goal > Agentic v4                                                  |
|   Epic > Always-on layer                                            |
|    Task #44  impl plan        AWAITING APPROVAL (!)        [open]    |
|    Task #41  spec-writing     in_review                            |
|    Task #39  builder run      merged                               |
|  filter: [(!) approval-gated] [scope:..] [status:..]               |
+- SIGNALS -----------------------------------------------------------+
|  Pattern P-7  "5 bugs in patterns.py this month"  [promote][dismiss]|
|  calibration  code-reviewer 0.38 (!) distrusted                    |
+---------------------------------------------------------------------+
```

Three panels: ticks/health, the board (tabbed by hierarchy level, filterable --
"filter by approval-gated" lands here), and signals (Patterns/ArchDebt/
calibration). Clicking a task opens its task sheet (full body, criteria, linked
nodes, review history, and the Approve/Decline/Retry + follow-up controls -- see
Section 6).

### Read model -- reuse, do not reinvent

The HUD imports the existing `agentic_mcp` read helpers (`queries.query_graph`,
`nodes.get_node`, `relations.neighbors`) to render the board straight from
`graph.db`. It does NOT reimplement DB access and NEVER writes `graph.db`
directly -- every mutation goes through the daemon's control API (the one audit
path). Live tick status comes from polling the daemon. Refresh: short poll
(1-2s) for health + a light change-check on the graph. No push infrastructure.

### Launch context = default screen

Started inside a project dir -> walk up to that `.agentic` and open its
workspace directly (mirrors the SessionStart hook). Started bare -> overview. So
"I just want to work in my project" costs zero detours.

### Tech choice -- Textual (Python TUI)

- Clickable/mouse-driven with real widgets and buttons (the "clickable commands"
  requirement).
- Terminal-native (a true companion HUD).
- Python -- reuses the exact `agentic_mcp` modules the rest of the system uses to
  read the graph, instead of duplicating schema knowledge in another language.
- Bonus: can later serve the same app in a browser via `textual-web` with no
  rewrite, if a non-terminal view is ever wanted.

Alternatives considered: a localhost web app (richer but heavier, not a "TUI")
and a Rust/Go TUI (no code reuse). Both cost more and buy less here.

### Failure behavior

Daemon down -> HUD still renders boards (it reads graphs directly) but greys out
live tick status and disables control buttons behind a "daemon offline" banner.
Read-only degradation, never a crash.

---

## 4. PM / board-management model

**The board is a view; the PM is a tick.** There is no separate board datastore
and no separate always-on PM agent. The board IS the `goal -> epic -> task ->
subtask` nodes in `graph.db`; "managing it" means a stateless PM tick reads those
nodes, mutates their status, and exits. The supervisor (R) fires the tick on
cadence; the HUD (H) renders it.

### The PM is a small family of stateless ticks

- `orchestrate.tick` -- existing scheduler/dispatcher (ready set, claim,
  dispatch, review, merge, escalate, weed).
- `promotion.tick` -- new (L): turns signals into board items (Section 5).

No new role, no daemon-resident logic.

### Segment vs schedule

- **Scheduling/placement = the PM tick.** Ordering by the DAG, claiming disjoint
  scopes, gating, dispatching, weeding, escalating. Deterministic, no LLM.
- **Decomposition = a planner the PM dispatches.** Turning a raw signal into
  structured epic/task/subtask + a plan is an LLM planning act. The PM never
  decomposes; it commissions decomposition, then tracks the result on the board.

So "segmented out by the PM" means: the PM places a candidate on the board and
dispatches a planner to give it structure -- it does not author the structure.

### Task lifecycle (the heart of board-management)

`task.status` is free-text in the schema (no CHECK constraint), so the new states
need NO migration -- just new string values and the transitions that honor them.

```
        promotion (L)            planner done
 signal ----------> candidate --------------> awaiting_approval  <- GATE (G)
                       |  (PM dispatches               |
                       |   planner)                    | user acts in HUD
                       v                               v
                    planning            +-- Approve --> pending
                                        +-- Retry ----> planning
                                        +-- Decline --> declined (closed)

   pending -> in_progress -> (review in-tick) -> merged       (normal
        ^          |                              ^            orchestrate
        +--retry<--+-- strike<3                   |            flow, exists)
                   +-- strike==3 -> escalated     |
```

New states/transitions are only `candidate`, `planning`, `awaiting_approval`,
`declined`, plus the three gate edges. Everything from `pending` rightward is the
orchestrator that already runs.

### What the PM tick does each fire (bold = new)

1. Weed stale nodes / flag stale specs. *(exists)*
2. **Skip any `awaiting_approval` task -- never dispatch past the gate.** *(new, G)*
3. Compute ready set from the DAG over `pending` tasks. *(exists)*
4. **Pick up freshly-`pending` (just-approved) tasks -> dispatch spec-writer.** *(new, G)*
5. Claim disjoint scopes, dispatch builders, review, merge/escalate. *(exists)*
6. **(promotion tick) mint candidates from new signals + dispatch planners.** *(new, L)*

### Board management is not the HUD

The HUD only shows the board and requests gate actions through the daemon API.
If the HUD is closed, the PM tick keeps managing the board headlessly -- planning
still happens, work still merges, escalations still accrue. The HUD is a window,
not the manager.

### No new board schema

Hierarchy tables exist; new statuses are free-text values; parent/child structure
uses existing relations (`implements`, `depends-on`). Approval notes / the
follow-up thread live in existing `Decision` nodes (Section 6) -- no new table.

---

## 5. L -- the auto-rehydration loop

The promotion tick -- a stateless tick in the PM family, fired by R on its own
cadence (e.g., every 30m). It bridges "the system noticed something" to "there is
a documented unit of work on the board."

### Inputs (signal sources)

- Confirmed `Pattern` nodes (from the pattern-finder).
- Triaged `ArchDebt` nodes (from sub-project B, when it lands).
- `Retro` nodes (postmortems -> bugfix/process candidates).
- Backlog `Finding`s triaged `backlog` (PR follow-ups).
- **Chat-created ideas** -- when the user asks a live session "make a task for X,"
  the session writes a candidate signal/task node via MCP, exactly like any other
  source. The promotion tick treats it identically.

### Tick flow, per eligible signal

```
for each eligible signal (confirmed/triaged, actionable):
  1. DEDUP GUARD: does a Task already exist derived-from this signal? -> skip
  2. mint a candidate Task node, link derived-from the signal
  3. dispatch the headless triage-planner against it
  4. planner classifies + right-sizes + documents:
        small -> one task sheet (Task+Spec)
        large -> Epic + N task sheets
     ...each with acceptance criteria, proposed approach,
        EXPLICIT assumptions, and an open-questions list
  5. status -> planning -> awaiting_approval when the sheet(s) are written
```

### The triage-planner -- a headless agent, NOT a skill invocation

The interactive `brainstorming` skill is user-gated (one question at a time) and
cannot run unattended. Consistent with the existing system (PRD D-29: tactical
practices embedded in subagent prompts, no cross-plugin references), the
signal-driven planner is a **headless agent with embedded intent-clarification +
right-sizing heuristics**. It never blocks on interactive Q&A; instead it states
its assumptions explicitly and lists its open questions, which the gate resolves.

**Two planner modes, kept distinct:**

- **Interactive planning (user present):** real back-and-forth brainstorming
  happens in a live chat session, with the user, before a sheet is finalized.
- **Unattended planning (signal-driven):** the headless triage-planner above.

### Output shape varies by signal type

| Signal shape | Planner output (the task sheet) |
|---|---|
| Bug / Retro-derived | repro + root-cause hypothesis + fix approach + criteria. Often one small sheet. |
| Feature / user idea | problem statement, scope (in/out), approach, criteria. The "implementation plan" shape. May be an Epic. |
| PR follow-up / backlog Finding | tightly-scoped change + criteria. Usually one sheet, sometimes auto-closeable. |
| ArchDebt | remediation proposal, frequently Epic-level -> decomposes into several sheets. |
| Pattern | often not directly buildable -> an investigation sheet or a process-change proposal, not code. |

### De-dup -- the graph does NOT do it automatically

- **Structural dedup (build now):** before minting a candidate, check whether a
  Task already exists `derived-from` this signal; if so, skip. Combined with
  Pattern triage status (`open -> confirmed/dismissed`), a confirmed-and-already-
  promoted signal never re-spawns. Cheap, deterministic, covers the common case.
- **Semantic dedup (deferred):** "two different signals describing the same work"
  needs similarity matching -- exactly what the `sqlite-vec` embedding index
  (deferred since Phase 0, `schema.sql:252`) was reserved for. Until it lands, the
  planner's triage flags a cheap title/scope-overlap suspicion for human review at
  the gate.

### Never-raise + idempotent

A planner failure on one signal is a logged outcome, not a crash -- the candidate
stays `candidate`/`planning` and retries next cadence (with a strike cap via the
existing CriticalLoop, so a chronically-unplannable signal escalates instead of
looping). Re-running the tick is safe because the dedup guard makes promotion
idempotent.

### Cost control (matters for a 24/7 service)

Planning compute is the main unattended spend. Two governors: (a) the dedup guard
prevents re-planning; (b) a per-cadence promotion **cap** (`promotion_cap` in the
registry) so a burst of findings cannot fan out into unbounded headless runs.

---

## 6. G -- the approval-gate workflow

The human control valve: where "the system planned something" meets "the user
decides if it is worth building."

### The gate state

A task sheet sits at `awaiting_approval`; the orchestrate tick refuses to dispatch
it past that point (Section 4, step 2). It can sit indefinitely -- no timeout, no
auto-approve. Building never happens without the user.

### The task-sheet review surface (HUD)

Opening a gated task shows the full sheet:

- The Task body (the unit of work) + its **draft Spec** (acceptance criteria,
  verify methods, feedback loop).
- The planner's **explicit assumptions** and **open-questions list** (deferred Q&A).
- The originating signal (`derived-from` link) -- why this exists.
- If an Epic: the child sheets it decomposes into.

### Three actions + optional notes

| Action | Transition | What happens |
|---|---|---|
| Approve | `awaiting_approval -> pending` | Enters the ready set; PM hands to the spec-writer to harden the draft Spec to dispatch-ready, then the build loop runs. |
| Decline | `awaiting_approval -> declined` | Closed (terminal). The `derived-from` link remains, so dedup prevents re-promotion. |
| Retry (+notes) | `awaiting_approval -> planning` | The triage-planner re-runs WITH the user's notes as input (the notes answer its open questions). |

Follow-up notes are optional on Approve, the whole point on Retry (the answers),
and a rationale record on Decline.

### Draft-spec -> approve -> harden-spec

This reconciles the user-story's "PM assigns a spec-writer AFTER approval." The
triage-planner writes a **draft** Spec -- good enough to review and decide on,
cheap to produce. Only after Approve does the spec-writer formalize it (run
`validate_spec`, tighten criteria, fill `required_reads`) so it passes the
dispatch gate. Payoff: no full spec-hardening cost for plans that get declined.
The planner makes it reviewable; the spec-writer makes it buildable; approval is
the line between.

### Where notes / the thread live -- no new table

Each gate action writes a `Decision` node (existing type: "a locked choice with
rationale") linked to the task, capturing verdict + notes + timestamp. Successive
Decisions (Retry -> Retry -> Approve) linked to the same task ARE the "follow-up
thread" -- a readable audit trail reusing existing node types.

### Audit path

All three actions go through the daemon's control API -> a single graph write
(Section 2), so there is one tamper-evident trail and the HUD never writes
statuses directly.

### The user story, traced end-to-end

```
1. User is in a live chat on feature A; an idea for feature B strikes.
2. "make a task to design feature B" -> the session writes a candidate
   signal node via MCP (chat = just another signal source).
3. promotion tick (L): dedup-guard passes -> mints candidate Task,
   derived-from the idea -> dispatches the headless triage-planner.
4. planner right-sizes B -> task sheet (or Epic+sheets) with draft Spec,
   assumptions, open questions -> status awaiting_approval.
5. User opens HUD -> project workspace -> Board -> filter approval-gated.
6. The finished sheet is there. User clicks in, reads it.
7. User clicks APPROVE, leaves notes empty -> Decision node written ->
   status pending.
8. PM tick picks up the pending task -> dispatches spec-writer ->
   Spec hardened to dispatch-ready -> build loop (builder + review) begins.
```

Every step is a graph write the HUD reflects live; nothing required the user to
be in a terminal session while the planning happened.

---

## 7. Build sequence, scope boundaries, risks

### Build sequence -- an incremental value ladder

Each rung ships standalone value and de-risks the next.

```
0. PREREQ  busy_timeout in db.connect          -> concurrent access safe
           (small, system-wide; was the deferred follow-up, now mandatory)

1. R       supervisor daemon + registry        -> "my existing system runs
           (fires EXISTING ticks on cadence)      on cadence, unattended"

2. H       HUD, read-only first                -> "...and I can watch it
           (overview + workspace from graph.db    live across projects"
            + daemon health)

3. G       approval gate + HUD control          -> "...and I can approve/
           (awaiting_approval, Decision nodes,    decline/retry gated work"
            control API, spec-writer-after-approve)

4. L       promotion tick + triage-planner      -> "...and it generates and
           (richest, most LLM-heavy, riskiest)    plans its own work"
```

Ordering is forced by dependencies: R is the keystone (H polls it; nothing fires
without it); H control needs the API R exposes; L must come after G or
auto-planned work has nowhere safe to park. Building L last means that by the time
the system generates its own work, the HUD exists to watch it and the gate exists
to stop it.

### Relationship to the rest of the roadmap

- **Sub-project B (architectural review)** -- proceeds as the currently-designated
  next build, independent of this vision. B is a *feeder*: it produces `ArchDebt`,
  a signal source for L. Neither blocks the other; they meet at the promotion tick.
- **Phase 4 (self-improvement)** -- L IS the Phase-4 closed loop ("the system
  changes itself in response to its own data"). This vision's key addition is the
  approval gate (G) as the safety valve: plan freely, never build unapproved.
- **Sub-project C (meta-graph)** -- out of scope. The HUD registry is designed so
  cross-project pattern detection plugs in later without rework (the Section 1
  seam). Aggregate *display* (registry + per-project graphs) is independent of
  cross-project *analysis* (the meta-graph).

### Top risks and mitigations

| Risk | Mitigation |
|---|---|
| Concurrent DB access (`database is locked`) | `busy_timeout` (rung 0) + the existing commit-barrier pattern; test with concurrent connections |
| Unattended token runaway | promotion cap + structural dedup; surface per-project spend in the HUD |
| Daemon dies silently | Task Scheduler keep-alive + heartbeat; HUD shows daemon-offline banner |
| Triage-planner emits weak sheets | the gate is the backstop; track approve/decline/retry rates as a planner-quality signal (reuse the calibration machinery) |
| Self-modifying changes slipping through | gate before build catches all of it; a later "configurable gate by risk" option could hard-gate self-modifying work specifically |

### Testing posture (unchanged from the proven pattern)

Every tick stays stateless + injectable-seam + unit-tested in the fast suite. The
daemon is tested with stubbed tick-spawns. The HUD is tested against a fixture
`graph.db`. Real `claude -p` paths are `llm`-marked e2e. The "fast suite is the
gate" model is preserved.

---

## Appendix: subsystem summary

| Sub | Name | One-line purpose | New vs existing |
|---|---|---|---|
| R | Supervisor daemon | Fire existing ticks on cadence, 24/7, OS-kept-alive; serve control API | New process; reuses ticks |
| H | Companion HUD | Master overview + per-project workspace; read graph, control via daemon | New (Textual) |
| PM | Board-management | Orchestrator-as-tick; segment-vs-schedule; task lifecycle + gate handling | Extends existing orchestrator |
| L | Auto-rehydration | Promotion tick + headless triage-planner; signal -> right-sized task sheet(s) | New tick + new agent |
| G | Approval gate | awaiting_approval state; Approve/Decline/Retry; draft-spec -> harden-spec | New states + workflow |
| C | Cross-project meta-graph | Cross-project pattern detection | Deferred (clean seam) |

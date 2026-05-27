# Rung 2 -- Companion HUD (read-only): Design

> **Type:** Implementation design / spec (feeds writing-plans next).
> **Date:** 2026-05-26
> **Rung:** 2 of the always-on companion value ladder (H, read-only first).
> **Depends on:** Rung 0 (busy_timeout in db.connect) + Rung 1 (supervisor daemon
>   + loopback control API), both merged to main (PR #4, commit 563bd38).
> **Parent vision:** docs/superpowers/specs/2026-05-25-always-on-companion-vision-design.md
>   Section 3 (H -- the HUD).
> **Status:** Design approved in brainstorming; pending user spec review before
>   writing-plans.

---

## 0. Why this rung exists

Rung 1 made the existing ticks fire on cadence, unattended. The user cannot yet
*see* any of it without opening a database. Rung 2 is the companion surface: a
Textual TUI that reads each project's graph.db directly and polls the daemon for
live tick status, so the value becomes "...and I can watch it live across
projects."

Read-only first. The HUD never writes graph.db. The only mutations it triggers
are process controls already exposed by the rung-1 loopback API (run-now,
pause, resume) -- these change ephemeral supervisor state, not durable graph
data. The approval gate (Approve/Decline/Retry, which DO write the graph) is
rung 3; its buttons render here but are disabled.

### Locked decisions (from this brainstorm)

1. **Graph-change detection = PRAGMA data_version.** One integer read per poll,
   purpose-built for "did another connection commit," WAL-safe. Forces one
   persistent read connection per project (a fresh connection per poll resets the
   counter and breaks the comparison).
2. **Refresh = single ~1.5s timer + thread worker.** One cadence; one shared
   daemon HTTP poll covers all projects; the board re-reads only when
   data_version advanced. Blocking I/O runs in a Textual thread worker, never on
   the event loop.
3. **Testing = two-layer.** Pure, Textual-free view-model functions carry the
   bulk of coverage in fast non-async unit tests; a thin set of Pilot tests
   covers widget rendering and input wiring with a stubbed daemon client.
4. **Read-only task sheet is in scope.** Click a board task -> full sheet (body,
   criteria, linked nodes, review history). Approve/Decline/Retry buttons render
   but are disabled (rung 3 enables them).
5. **Architecture = layered (view-models + GraphSource + DaemonClient + thin
   Textual).** Not Textual-centric reactive widgets (untestable without Pilot),
   not a separate package (packaging friction for no gain).
6. **Packaging = agentic_mcp.hud subpackage; textual as optional extra.**
   Importing agentic_mcp never pulls Textual; only agentic_mcp.hud does.

---

## 1. Module layout and packaging

```
mcp-server/src/agentic_mcp/hud/
  __init__.py
  __main__.py       # main(): arg parsing, launch-context resolution, run app
  app.py            # AgenticHUD(App): screen stack, refresh worker, bindings
  screens.py        # OverviewScreen, WorkspaceScreen
  task_sheet.py     # TaskSheet(ModalScreen) -- read-only drill-in
  view_models.py    # pure functions + dataclasses (NO textual import)
  graph_source.py   # GraphSource: persistent read conn + data_version probe
  daemon_client.py  # DaemonClient: loopback HTTP + DAEMON_OFFLINE sentinel
```

- `pyproject.toml`: add `[project.optional-dependencies] hud = ["textual>=N"]`
  (pin the concrete floor during planning) and console script
  `agentic-hud = "agentic_mcp.hud.__main__:main"`.
- `view_models.py`, `graph_source.py`, `daemon_client.py` are **Textual-free**.
  That isolation is what keeps the majority of tests fast and non-async, and lets
  `import agentic_mcp` stay zero-cost for everything that is not the HUD.

---

## 2. View-model layer (pure -- the primary test surface)

Plain dataclasses plus functions over a graph connection and/or a daemon
snapshot. No Textual. Built on the EXISTING read helpers
(`queries.query_graph`, `queries.walk_down`, `nodes.get_node`,
`relations.neighbors`) and the existing calibration read -- never reimplemented
DB access.

| Function | Returns | Built from |
|---|---|---|
| `overview_view(registry, daemon_snapshot, sources)` | `list[OverviewRow]` | registry (cfg.load_registry) + daemon snapshot per project + per-project graph counts |
| `board_view(conn)` | `BoardModel` | `query_graph(type="Goal")` roots + `walk_down` for epic/task/subtask |
| `signals_view(conn)` | `SignalsModel` | `query_graph` for Pattern / ArchDebt / backlog Finding + calibration read |
| `task_sheet_view(conn, task_id)` | `TaskSheetModel` | `get_node` + draft Spec (criteria_json) + `neighbors` links + linked Review nodes |

- `OverviewRow`: project name, path, enabled, paused, tick-status summary (from
  daemon snapshot), `gated_count` (`query_graph(type="Task",
  status="awaiting_approval")` -- 0 until rung 3 produces that state, query is
  forward-compatible), `escalation_count` (escalated tasks / CriticalLoop nodes),
  last-activity timestamp.
- `BoardModel`: the goal-rooted hierarchy built ONCE, carrying per-level lists so
  the tabbed view (Goals | Epics | Tasks | Subtasks) and the status / scope /
  approval-gated filters are pure selections over the built model (no re-query
  per tab/filter).
- `SignalsModel`: Patterns, ArchDebt (EMPTY list until sub-project B lands --
  rendered as "none", never an error), backlog Findings, and calibration
  entries (e.g. distrusted reviewer scores). Note: `calibration.get_calibration`
  is per-role, so signals_view reads the configured roles and surfaces the
  distrusted ones; review history uses the existing `review` table (verdict
  column) linked to the task via `neighbors`.
- `TaskSheetModel`: task body, the draft Spec and its acceptance criteria, the
  `derived-from` originating signal, the `implements` parent, and review history.

All four are unit-tested directly against a fixture graph.db -- no Textual, no
daemon, no async.

---

## 3. GraphSource (per project)

- Opens ONE persistent read connection via the existing `db.connect` (inherits
  the rung-0 `busy_timeout`). Open question deferred to planning: also pass a
  `mode=ro` URI as a hard guardrail against accidental writes. Either way the HUD
  issues no writes; tests assert the read-only contract.
- `changed() -> bool`: reads `PRAGMA data_version`, compares to the stored prior
  value, updates it, returns whether it advanced. This is the per-poll gate that
  decides whether the board view-models are rebuilt.
- Exposes `conn` for view-model reads; `close()` on app exit.
- The overview holds one `GraphSource` per registered project; the workspace
  holds the single active project's source.

---

## 4. DaemonClient (the one seam to the daemon)

- `base_url` resolution order: `--port` flag -> `AGENTIC_SUPERVISOR_PORT` env ->
  default `8787` (the daemon's fixed `run_forever` default). `timeout` ~0.5s so a
  hung daemon cannot stall a refresh tick.
- Methods: `snapshot() -> DaemonSnapshot | DAEMON_OFFLINE` (`GET /projects`, which
  carries `beat_at`, so it doubles as the health probe), `run(path, tick)`,
  `pause(path)`, `resume(path)` (the existing `POST` controls).
- Any `ConnectionError` / timeout / non-200 -> returns the `DAEMON_OFFLINE`
  sentinel; it NEVER raises into the UI.
- Approve / Decline / Retry are deliberately NOT methods here -- those endpoints
  do not exist until rung 3.
- This client is the injected stub in Pilot tests (no real HTTP server in the
  gate suite).

---

## 5. Textual app, data flow, and refresh

### Screens

- `OverviewScreen` -- the only cross-project surface: a table, one row per
  registered project, rendered from `overview_view`. Bindings: `enter` open
  workspace, `r` run-now, `space` pause/resume, `a` add project (deferred -- see
  Section 8).
- `WorkspaceScreen` -- the canonical surface, three panels:
  1. ticks/health strip (from the daemon snapshot for this project),
  2. the board (tabbed by level, filterable; from `board_view`),
  3. signals (from `signals_view`).
- `TaskSheet(ModalScreen)` -- pushed when a board task row is activated; renders
  `task_sheet_view`. Approve / Decline / Retry buttons present but disabled with
  a "rung 3" tooltip.

### Launch context (in `__main__.main`)

- Started inside a project dir -> walk up to its `.agentic`, push
  `WorkspaceScreen` for that project directly (mirrors the SessionStart hook).
- Started bare -> push `OverviewScreen`.
- `enter` opens a workspace from the overview; `esc` pops back to the overview.

### Refresh loop

- A single `set_interval` (default **1.5s**, a single named constant) fires a
  Textual **thread worker** that:
  1. calls `DaemonClient.snapshot()` once (covers all projects), and
  2. calls `changed()` on the visible screen's `GraphSource`(s).
- The worker posts a message back to the UI thread. The tick/health strip and
  overview tick-status update every tick (cheap); the board and signals
  view-models are rebuilt ONLY when `data_version` advanced for that project.
- The event loop never blocks on HTTP or a locked DB -- all blocking I/O is in
  the worker.

### Controls

- run-now / pause / resume call `DaemonClient`; the result refreshes on the next
  tick (or an immediate forced poll).
- Approve / Decline / Retry render but are disabled (rung 3).

---

## 6. Failure behavior

- **Daemon down** (`DAEMON_OFFLINE`): a "daemon offline" banner shows; the
  tick/health strip greys out and run/pause/resume disable -- but boards, signals,
  and the task sheet still render from graph.db, because the read path is
  independent of the daemon. Read-only degradation, never a crash.
- **A project's graph.db missing or locked**: that overview row / workspace panel
  renders as unavailable (with the reason) without taking down the app; other
  projects are unaffected.
- The HUD inherits the never-raise spirit at its edges: a malformed node, a
  missing Spec, or an absent ArchDebt table degrades to "none"/"unavailable",
  never an exception that reaches the user.

---

## 7. Testing posture (two-layer)

### Fast, non-async (the bulk; the gate)

- View-model functions against a fixture graph.db builder: assert
  `overview_view`, `board_view`, `signals_view`, `task_sheet_view` produce the
  expected dataclasses for known fixtures, including the degrade-to-empty cases
  (no ArchDebt, no Spec, no signals).
- `GraphSource.changed()` against a real temp DB: write via a SECOND connection,
  assert the probe flips true exactly once then false.
- `DaemonClient` offline fallback: point at a closed port / stub the transport,
  assert `DAEMON_OFFLINE` and that control methods do not raise.

### Thin Pilot (async)

- `app.run_test()` with a STUBBED `DaemonClient` and a fixture `GraphSource`:
  assert the board renders expected rows, filters narrow them, `enter`/`esc`
  navigate, a task-row activation opens the sheet, and run/pause/resume invoke
  the stub. This subset adds an async-capable runner to the fast suite; it stays
  under `-m "not llm"`.

### Not in the gate suite

- No real `claude -p`, no real HTTP server, no real daemon. (A live smoke test of
  `agentic-hud` against a running daemon can be an `llm`/manual-marked extra, not
  part of the fast gate.)

---

## 8. Scope boundary

### In rung 2

Overview screen; workspace screen (3 panels); read-only task sheet; run-now /
pause / resume controls wired to the existing loopback API; daemon-offline and
missing-DB degradation; the full read/view-model + GraphSource + DaemonClient
layering; the two-layer test suite.

### Out (rung 3 and later)

- Approve / Decline / Retry wiring; the `awaiting_approval` task state being
  *produced*; `Decision`-node writes; ANY graph mutation. The
  `gated_count` / `awaiting_approval` *reads* exist now (forward-compatible) and
  simply show 0 until rung 3 produces that state.
- "Add project" (`a` on the overview) -- registration is a control-API concern
  that pairs with rung-3 write flows; the binding may be present but disabled, or
  deferred entirely (decide in planning).
- SVG snapshot tests, textual-web browser serving, cross-project meta-graph
  display -- all explicitly deferred.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Persistent read connection interferes with daemon writers | rung-0 busy_timeout + WAL-friendly short reads; an idle read connection holds no lock; covered by a concurrent-write test |
| data_version comparison broken by reconnect | GraphSource holds ONE long-lived connection for its lifetime; tested explicitly |
| Slow/hung daemon stalls the UI | 0.5s client timeout + all polling in a thread worker; DAEMON_OFFLINE fallback |
| Textual API churn | pin a textual floor in the hud extra; keep widgets thin so an upgrade touches little |
| TUI hard to test | two-layer split puts logic in pure functions; Pilot covers only wiring |
| Custom daemon port | --port / env override on the HUD; default matches the daemon default 8787 |

---

## 10. Relationship to the ladder

Rung 2 consumes rung 1 (polls its control API) and rung 0 (concurrent-safe
reads). It produces the surface that rungs 3 and 4 need: rung 3 turns the
disabled gate buttons live and adds the write endpoints; rung 4 (auto-rehydration)
fills the board with auto-planned `awaiting_approval` work the HUD already knows
how to display. Building the HUD read-only first means that when the gate and the
promotion loop arrive, there is already a window to watch them through.

# Phase 1 Build Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the four-role review team, four-tier severity, the autonomous critical-loop with stopping rules + 3-iteration diagnostic, layer-tagged Retros, and a spec-writer subagent to the agentic-engineering plugin — proven by a real-agent exit-gate test.

**Architecture:** Loop *state* lives in the MCP server (new `CriticalLoop` entity + tools); loop *control flow* lives in the `/agentic:review-pr` command executed on the Claude side (MCP servers cannot dispatch subagents). Per round, agents fire gate-then-parallel: spec-checker first; if it passes, code-reviewer + contrarian run in parallel, blind to each other.

**Tech Stack:** Python 3.12 (`mcp-server/.venv`), `mcp==1.27.1` pinned, plain SQLite (no extensions), PowerShell 5.1 hooks/scripts, Claude Code subagents (markdown) + slash commands (markdown). Windows-only.

**Source design:** `docs/plans/2026-05-20-phase-1-build-pipeline-design.md` (all 11 locked decisions; Spec §13 passed `validate_spec`).

**Plan discipline:** Apply every section of `docs/plans/PLAN-TEMPLATE-CHECKLIST.md`. Notably: `git commit -F <tempfile>` (never `-m` heredoc — PS5.1 word-splits to native exes); `python <tempfile>.py` (never `python -c "..."` — PSNativeCommand strips embedded quotes); no exact test counts ("suite green"); `.ps1` ASCII-only inside `"..."` + parse-check before commit; validators and their tests share fixtures; one commit per task; maintain the `.tasks.json` sidecar per task.

---

## Phase 0 reality corrections (verified against source 2026-05-20 — DO NOT re-litigate)

1. **`failed_layer` already ships.** `retro` table has the enum CHECK (`mcp-server/src/agentic_mcp/schema.sql:181-194`); `create_node` accepts it (`nodes.py:39`); `agents/builder.md` already writes it. Phase 1 adds only a `log_retro` convenience wrapper — **no schema migration for `failed_layer`.**
2. **No single `nodes` table.** Each entity type has its own table (`goal`, `spec`, `finding`, `retro`, ...). A new entity = a new table + an `ENTITY_TABLES` registration in `nodes.py` + (optionally) `EXTRA_REQUIRED`/`EXTRA_OPTIONAL` entries.
3. **`relations` CHECK is closed** (`schema.sql:213-216`): `implements, depends-on, blocks, supersedes, caused-by, observed-in, touches, references, derived-from`. It does **not** include `tracks`, and SQLite cannot `ALTER` a CHECK without rebuilding the table. **Decision: link CriticalLoop→Finding via a `finding_id` column on `critical_loop`, not a relation.** No `relations` change needed.
4. **Phase 0 has no migration framework.** `db.init_db` runs `schema.sql` (all `CREATE TABLE IF NOT EXISTS`). Phase 1 introduces a small idempotent migration module gated by `PRAGMA user_version`.
5. **Phase 0's e2e test simulates the spec-checker in pure Python** (`tests/test_e2e_bootstrap.py` subprocesses `pytest`). It does **not** invoke real agents. Phase 1's exit-gate test is genuinely new infrastructure: it subprocesses the real `claude` CLI.

---

## File Structure

**New source files:**
- `mcp-server/src/agentic_mcp/migrations.py` — idempotent Phase 1 schema migration (user_version gated)
- `mcp-server/src/agentic_mcp/loops.py` — CriticalLoop lifecycle (start/advance/resolve/get_open)
- `mcp-server/src/agentic_mcp/dispatch.py` — `dispatch_spec` + post-dispatch criteria-immutability check

**Modified source files:**
- `mcp-server/src/agentic_mcp/db.py` — call `migrations.apply_migrations` from `connect` + `init_db`
- `mcp-server/src/agentic_mcp/nodes.py` — register `CriticalLoop` in `ENTITY_TABLES` / required / optional
- `mcp-server/src/agentic_mcp/findings.py` — add `record_triage` + `log_retro`
- `mcp-server/src/agentic_mcp/validators.py` — add `validate_dispatched_immutable`
- `mcp-server/src/agentic_mcp/server.py` — register new tools (list_tools + call_tool)

**New agent files:** `agents/code-reviewer.md`, `agents/contrarian.md`, `agents/spec-writer.md` (+ modify `agents/builder.md`)

**New command files:** `commands/dispatch.md`, `commands/review-pr.md` (+ optional `commands/new-spec.md`)

**New skill file (if prompt-bloat budget exceeded):** `skills/reviewing/SKILL.md`

**New test files:** `test_migrations.py`, `test_critical_loop.py`, `test_dispatch_immutability.py`, `test_triage.py`, `test_retro_layer.py`, `test_stability_check.py`, `test_phase1_e2e.py` (+ additions to `test_server.py`)

**Layers (dependency order):** L1 persistence (Tasks 0-6) → L2 agents (7-10) → L3 commands (11-13) → L4 exit-gate test (14-16) → L5 stability + docs (17-18).

---

## Task 0: Pre-flight audit + Phase 1 migration module

**Goal:** An idempotent, additive migration that upgrades an existing Phase 0 `graph.db` (and fresh DBs) with the `dispatched_at`, `criterion_index`, `loop_iteration`, `triage` columns and the `critical_loop` table, gated by `PRAGMA user_version`.

**Files:**
- Create: `mcp-server/src/agentic_mcp/migrations.py`
- Modify: `mcp-server/src/agentic_mcp/db.py`
- Test: `mcp-server/tests/test_migrations.py`

**Acceptance Criteria:**
- [ ] Migration applies cleanly to a fresh DB and to a DB created from Phase 0 `schema.sql`.
- [ ] Running the migration twice is a no-op (idempotent) — second run adds nothing and does not error.
- [ ] `PRAGMA user_version` is `1` after migration.
- [ ] Pre-flight: `git status` reviewed; nothing that shouldn't ship is staged.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Pre-flight git-add audit (PLAN-TEMPLATE-CHECKLIST §1).**

Run `git status` and confirm `.agentic/`, `.venv/`, `__pycache__/`, `.pytest_cache/` are gitignored and no secrets/local artifacts are staged. Do NOT `git add .` later — stage named files only.

- [ ] **Step 2: Write the failing test.**

```python
# mcp-server/tests/test_migrations.py
"""Phase 1 migration: idempotent, additive, applies to fresh + Phase 0 DBs."""
from agentic_mcp import db, migrations


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_db_gets_phase1_schema(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        assert "dispatched_at" in _columns(conn, "spec")
        assert {"criterion_index", "loop_iteration", "triage"} <= _columns(conn, "finding")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "critical_loop" in tables
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        before = _columns(conn, "finding")
        migrations.apply_migrations(conn)  # second explicit run
        after = _columns(conn, "finding")
        assert before == after
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        conn.close()


def test_upgrades_phase0_db(tmp_db_path):
    # Simulate a Phase 0 DB: run only schema.sql, leave user_version at 0.
    import sqlite3
    from pathlib import Path
    schema = (Path(db.__file__).with_name("schema.sql")).read_text(encoding="utf-8")
    raw = sqlite3.connect(str(tmp_db_path))
    raw.executescript(schema)
    raw.commit()
    raw.close()
    # Now open via db.connect, which must migrate it.
    conn = db.connect(tmp_db_path)
    try:
        assert "dispatched_at" in _columns(conn, "spec")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        conn.close()
```

- [ ] **Step 3: Run test to verify it fails.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_mcp.migrations'`.

- [ ] **Step 4: Write the migration module.**

```python
# mcp-server/src/agentic_mcp/migrations.py
"""Phase 1 schema migrations. Idempotent + additive. user_version gated.

Phase 0 left schema in schema.sql (all CREATE TABLE IF NOT EXISTS) with
user_version 0. Phase 1 layers additive columns + the critical_loop table on
top. Safe to call on every connect(): returns immediately when already at the
target version.
"""
from __future__ import annotations

import sqlite3

PHASE_1_VERSION = 1

_CRITICAL_LOOP_DDL = """
CREATE TABLE IF NOT EXISTS critical_loop (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='CriticalLoop'),
  status TEXT NOT NULL CHECK(status IN ('open','resolved','escalated')),
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  finding_id TEXT NOT NULL,
  iteration_count INTEGER NOT NULL DEFAULT 1,
  started_at TEXT NOT NULL,
  diagnostic_fired_at TEXT,
  resolved_at TEXT
);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(conn, table: str, col: str, decl: str) -> None:
    if col not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def apply_migrations(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] >= PHASE_1_VERSION:
        return
    _add_column_if_missing(conn, "spec", "dispatched_at", "TEXT")
    _add_column_if_missing(conn, "finding", "criterion_index", "INTEGER")
    _add_column_if_missing(conn, "finding", "loop_iteration", "INTEGER")
    _add_column_if_missing(
        conn, "finding", "triage",
        "TEXT CHECK(triage IN ('fix-in-pr','backlog'))",
    )
    conn.executescript(_CRITICAL_LOOP_DDL)
    conn.execute(f"PRAGMA user_version = {PHASE_1_VERSION}")
    conn.commit()
```

- [ ] **Step 5: Hook the migration into `db.py`.**

Modify `mcp-server/src/agentic_mcp/db.py` — import migrations and call from both `connect` and `init_db`:

```python
from . import migrations  # add near top, after sqlite3/Path imports


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection. Caller manages close()."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    migrations.apply_migrations(conn)  # upgrade existing DBs on open
    return conn


def init_db(path: str | Path) -> None:
    """Create the DB file and apply schema. Idempotent."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        with _SCHEMA_PATH.open("r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        migrations.apply_migrations(conn)  # layer Phase 1 on fresh schema
    finally:
        conn.close()
```

Note: `connect` already calls `apply_migrations`, but the fresh-DB path runs `executescript(schema.sql)` *after* connect, which resets nothing (user_version persists). The explicit second call in `init_db` ensures the new columns exist after the Phase 0 schema is laid down. The `user_version>=1` guard makes the double-call a no-op.

- [ ] **Step 6: Run test to verify it passes.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q`
Expected: suite green.

- [ ] **Step 7: Confirm the full suite still passes (Phase 0 regressions).**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -q`
Expected: suite green (Phase 0 + new migration tests).

- [ ] **Step 8: Commit (via tempfile — PLAN-TEMPLATE-CHECKLIST §3).**

```powershell
$msg = "feat(schema): Phase 1 migration module (user_version gated, additive)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding utf8
git add mcp-server/src/agentic_mcp/migrations.py mcp-server/src/agentic_mcp/db.py mcp-server/tests/test_migrations.py
git commit -F $f
Remove-Item $f
```

---

## Task 1: Register the CriticalLoop entity in nodes.py

**Goal:** `create_node`, `update_node`, and `get_node` work for `CriticalLoop` so the lifecycle module (Task 2) can use the standard CRUD path.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/nodes.py`
- Test: `mcp-server/tests/test_critical_loop.py` (entity-registration portion; lifecycle added in Task 2)

**Acceptance Criteria:**
- [ ] `create_node(conn, "CriticalLoop", ...)` inserts a row with `finding_id`, `iteration_count`, `started_at`.
- [ ] `get_node` round-trips a CriticalLoop by id.
- [ ] Missing `finding_id` / `started_at` raises the standard "missing required field(s)" `ValueError`.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_critical_loop.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the failing test.**

```python
# mcp-server/tests/test_critical_loop.py
"""CriticalLoop entity registration + (Task 2) lifecycle."""
import pytest

from agentic_mcp import db, nodes


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def test_create_and_get_critical_loop(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        lid = nodes.create_node(
            conn, "CriticalLoop", status="open", owner="system",
            body="loop for finding X", finding_id="find-123",
            started_at="2026-05-20T00:00:00+00:00",
        )
        row = nodes.get_node(conn, lid)
        assert row is not None
        assert row["type"] == "CriticalLoop"
        assert row["finding_id"] == "find-123"
        assert row["iteration_count"] == 1  # column default
    finally:
        conn.close()


def test_critical_loop_requires_finding_id(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        with pytest.raises(ValueError, match="missing required field"):
            nodes.create_node(
                conn, "CriticalLoop", status="open", owner="system",
                body="loop", started_at="2026-05-20T00:00:00+00:00",
            )
    finally:
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_critical_loop.py -q`
Expected: FAIL — `ValueError: unknown entity type: CriticalLoop`.

- [ ] **Step 3: Register the entity in `nodes.py`.**

Add to `ENTITY_TABLES`:

```python
    "ArchDebt": "arch_debt",
    "CriticalLoop": "critical_loop",   # ADD THIS LINE
}
```

Add to `EXTRA_REQUIRED`:

```python
EXTRA_REQUIRED = {
    "Spec": {"criteria_json", "feedback_loop"},
    "Finding": {"severity", "parent_id"},
    "File": {"path"},
    "CriticalLoop": {"finding_id", "started_at"},   # ADD THIS LINE
}
```

Add to `EXTRA_OPTIONAL`:

```python
EXTRA_OPTIONAL = {
    "Spec": {"required_reads"},
    "Finding": {"subtype"},
    "Retro": {"failed_layer"},
    "Review": {"verdict"},
    "CriticalLoop": {"iteration_count", "diagnostic_fired_at", "resolved_at"},  # ADD
}
```

Note: `iteration_count` has a column DEFAULT of 1, so omitting it on insert yields 1. `_all_cols_for` will include it when present in `fields`; when absent, the INSERT omits it and SQLite applies the default.

- [ ] **Step 4: Run test to verify it passes.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_critical_loop.py -q`
Expected: suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(nodes): register CriticalLoop entity (table + CRUD)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding utf8
git add mcp-server/src/agentic_mcp/nodes.py mcp-server/tests/test_critical_loop.py
git commit -F $f
Remove-Item $f
```

---

## Task 2: Critical-loop lifecycle module

**Goal:** `loops.py` providing `start_critical_loop`, `advance_critical_loop` (fires the 3-iteration diagnostic flag), `resolve_critical_loop`, and `get_open_loops`, all surviving a fresh DB connection.

**Files:**
- Create: `mcp-server/src/agentic_mcp/loops.py`
- Test: `mcp-server/tests/test_critical_loop.py` (append lifecycle tests)

**Acceptance Criteria:**
- [ ] `start_critical_loop(conn, finding_id)` creates an `open` loop at iteration 1, returns loop_id.
- [ ] `advance_critical_loop` increments `iteration_count`; on reaching 3 it sets `diagnostic_fired_at` (once, not re-stamped on 4+).
- [ ] `resolve_critical_loop` sets `status='resolved'` and `resolved_at`.
- [ ] `get_open_loops` returns only `open` loops; survives close/reopen of the DB.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_critical_loop.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the failing tests (append to `test_critical_loop.py`).**

```python
from agentic_mcp import findings, loops


def _spec_with_finding(conn):
    import json
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
        feedback_loop="if a user reports a bug we open a PR and write a retro",
    )
    fid = findings.log_finding(conn, spec_id, "Critical", body="boom")
    return spec_id, fid


def test_start_and_get_open_loops(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        _, fid = _spec_with_finding(conn)
        lid = loops.start_critical_loop(conn, fid)
        opens = loops.get_open_loops(conn)
        assert [l["id"] for l in opens] == [lid]
        assert opens[0]["iteration_count"] == 1
    finally:
        conn.close()


def test_advance_fires_diagnostic_at_three(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        _, fid = _spec_with_finding(conn)
        lid = loops.start_critical_loop(conn, fid)
        loops.advance_critical_loop(conn, lid)  # -> 2
        assert nodes.get_node(conn, lid)["diagnostic_fired_at"] is None
        loops.advance_critical_loop(conn, lid)  # -> 3, fires
        stamped = nodes.get_node(conn, lid)["diagnostic_fired_at"]
        assert stamped is not None
        loops.advance_critical_loop(conn, lid)  # -> 4, NOT re-stamped
        assert nodes.get_node(conn, lid)["diagnostic_fired_at"] == stamped
    finally:
        conn.close()


def test_resolve_then_survives_reopen(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    _, fid = _spec_with_finding(conn)
    lid = loops.start_critical_loop(conn, fid)
    loops.resolve_critical_loop(conn, lid)
    conn.close()
    conn2 = db.connect(tmp_db_path)
    try:
        assert loops.get_open_loops(conn2) == []
        assert nodes.get_node(conn2, lid)["status"] == "resolved"
        assert nodes.get_node(conn2, lid)["resolved_at"] is not None
    finally:
        conn2.close()
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_critical_loop.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_mcp.loops'`.

- [ ] **Step 3: Write `loops.py`.**

```python
# mcp-server/src/agentic_mcp/loops.py
"""CriticalLoop lifecycle: start -> advance (diagnostic at iter 3) -> resolve.

State only. The loop CONTROL FLOW lives in the /agentic:review-pr command on the
Claude side; an MCP server cannot dispatch subagents.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import nodes

DIAGNOSTIC_THRESHOLD = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_critical_loop(conn: sqlite3.Connection, finding_id: str) -> str:
    finding = nodes.get_node(conn, finding_id)
    if finding is None or finding["type"] != "Finding":
        raise ValueError(f"not a Finding node: {finding_id}")
    return nodes.create_node(
        conn, "CriticalLoop", status="open", owner="system",
        body=f"critical loop tracking finding {finding_id}",
        finding_id=finding_id, started_at=_now(),
        scope=finding.get("scope"),
    )


def advance_critical_loop(conn: sqlite3.Connection, loop_id: str) -> dict:
    loop = nodes.get_node(conn, loop_id)
    if loop is None or loop["type"] != "CriticalLoop":
        raise ValueError(f"not a CriticalLoop node: {loop_id}")
    new_count = (loop["iteration_count"] or 1) + 1
    fields = {"iteration_count": new_count}
    if new_count >= DIAGNOSTIC_THRESHOLD and not loop.get("diagnostic_fired_at"):
        fields["diagnostic_fired_at"] = _now()
    nodes.update_node(conn, loop_id, **fields)
    return nodes.get_node(conn, loop_id)


def resolve_critical_loop(conn: sqlite3.Connection, loop_id: str) -> None:
    loop = nodes.get_node(conn, loop_id)
    if loop is None or loop["type"] != "CriticalLoop":
        raise ValueError(f"not a CriticalLoop node: {loop_id}")
    nodes.update_node(conn, loop_id, status="resolved", resolved_at=_now())


def get_open_loops(conn: sqlite3.Connection, scope: str | None = None) -> list[dict]:
    sql = "SELECT id FROM critical_loop WHERE status='open'"
    params: list = []
    if scope is not None:
        sql += " AND scope=?"
        params.append(scope)
    sql += " ORDER BY started_at"
    ids = [r[0] for r in conn.execute(sql, params)]
    return [nodes.get_node(conn, i) for i in ids]
```

- [ ] **Step 4: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_critical_loop.py -q`
Expected: suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(loops): CriticalLoop lifecycle (start/advance/resolve/get_open, diagnostic at iter 3)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding utf8
git add mcp-server/src/agentic_mcp/loops.py mcp-server/tests/test_critical_loop.py
git commit -F $f
Remove-Item $f
```

---

## Task 3: dispatched_at + dispatch_spec + criteria immutability

**Goal:** `dispatch.py` with `dispatch_spec(conn, spec_id)` (sets `dispatched_at`) and a `validate_dispatched_immutable` check that rejects any criteria text/order/count change once a spec is dispatched, pointing at supersede.

**Files:**
- Create: `mcp-server/src/agentic_mcp/dispatch.py`
- Modify: `mcp-server/src/agentic_mcp/validators.py` (add `validate_dispatched_immutable`)
- Test: `mcp-server/tests/test_dispatch_immutability.py`

**Acceptance Criteria:**
- [ ] `dispatch_spec` sets `dispatched_at` on the spec; second dispatch is a no-op (does not re-stamp).
- [ ] Editing a dispatched spec's criteria (text, order, or count) is rejected with a message naming supersede.
- [ ] Editing criteria on a NOT-yet-dispatched spec is allowed.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_dispatch_immutability.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the failing test (fixtures shared with the validator — PLAN-TEMPLATE-CHECKLIST §4).**

```python
# mcp-server/tests/test_dispatch_immutability.py
import json
import pytest

from agentic_mcp import db, dispatch, nodes, validators

_CRIT = [
    {"text": "basic", "verify": "pytest test_x.py::test_basic -q"},
    {"text": "edge", "verify": "pytest test_x.py::test_edge -q"},
]
_FB = "if a user reports a bug we open a PR and write a retro"


def _mk_spec(conn):
    return nodes.create_node(
        conn, "Spec", status="open", owner="t", body="spec",
        criteria_json=json.dumps(_CRIT), feedback_loop=_FB,
    )


def test_dispatch_sets_timestamp_once(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        sid = _mk_spec(conn)
        dispatch.dispatch_spec(conn, sid)
        first = nodes.get_node(conn, sid)["dispatched_at"]
        assert first is not None
        dispatch.dispatch_spec(conn, sid)  # no-op
        assert nodes.get_node(conn, sid)["dispatched_at"] == first
    finally:
        conn.close()


def test_dispatched_criteria_are_immutable(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        sid = _mk_spec(conn)
        dispatch.dispatch_spec(conn, sid)
        changed = [dict(_CRIT[0]), {"text": "NEW", "verify": "pytest test_x.py::test_new -q"}]
        ok, reasons = validators.validate_dispatched_immutable(conn, sid, changed)
        assert not ok
        assert any("supersede" in r.lower() for r in reasons)
    finally:
        conn.close()


def test_predispatch_criteria_mutable(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        sid = _mk_spec(conn)  # not dispatched
        changed = [dict(_CRIT[0])]
        ok, reasons = validators.validate_dispatched_immutable(conn, sid, changed)
        assert ok, reasons
    finally:
        conn.close()
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_dispatch_immutability.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_mcp.dispatch'`.

- [ ] **Step 3: Write `dispatch.py`.**

```python
# mcp-server/src/agentic_mcp/dispatch.py
"""dispatch_spec: stamp dispatched_at (drives criteria immutability)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import nodes


def dispatch_spec(conn: sqlite3.Connection, spec_id: str) -> str:
    spec = nodes.get_node(conn, spec_id)
    if spec is None or spec["type"] != "Spec":
        raise ValueError(f"not a Spec node: {spec_id}")
    if spec.get("dispatched_at"):
        return spec["dispatched_at"]  # already dispatched, no-op
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nodes.update_node(conn, spec_id, dispatched_at=stamp)
    return stamp
```

- [ ] **Step 4: Add `validate_dispatched_immutable` to `validators.py`.**

```python
# append to mcp-server/src/agentic_mcp/validators.py
import sqlite3  # add to imports at top


def validate_dispatched_immutable(
    conn: "sqlite3.Connection", spec_id: str, new_criteria: list[dict]
) -> tuple[bool, list[str]]:
    """Reject criteria changes on an already-dispatched spec.

    Compares (text, verify, order, count) of new_criteria against the stored
    criteria. If the spec is not dispatched, always passes.
    """
    from . import nodes
    spec = nodes.get_node(conn, spec_id)
    if spec is None or spec["type"] != "Spec":
        return False, [f"not a Spec node: {spec_id}"]
    if not spec.get("dispatched_at"):
        return True, []
    stored = json.loads(spec["criteria_json"])
    stored_sig = [(c.get("text"), c.get("verify")) for c in stored]
    new_sig = [(c.get("text"), c.get("verify")) for c in new_criteria]
    if stored_sig != new_sig:
        return False, [
            f"spec {spec_id} was dispatched at {spec['dispatched_at']}; criteria "
            "cannot change after dispatch. Create a new Spec with a 'supersedes' "
            "relation to this one instead."
        ]
    return True, []
```

- [ ] **Step 5: Run to verify pass, then full suite.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_dispatch_immutability.py -q`
Expected: suite green.
Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -q`
Expected: suite green.

- [ ] **Step 6: Commit.**

```powershell
$msg = "feat(dispatch): dispatched_at stamp + post-dispatch criteria immutability"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding utf8
git add mcp-server/src/agentic_mcp/dispatch.py mcp-server/src/agentic_mcp/validators.py mcp-server/tests/test_dispatch_immutability.py
git commit -F $f
Remove-Item $f
```

---

> **Installment 1 ends here (Tasks 0-3 — persistence spine).** Remaining tasks to be appended: Task 4 (finding triage columns + `record_triage`), Task 5 (`log_retro`), Task 6 (register all new tools in `server.py`), Tasks 7-10 (agents), Tasks 11-13 (commands), Tasks 14-16 (exit-gate test), Tasks 17-18 (stability check + docs). The `.tasks.json` sidecar and native tasks are created as each installment lands.

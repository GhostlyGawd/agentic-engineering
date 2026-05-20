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
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject (bit commit 7d2c0fe)
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
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject (bit commit 7d2c0fe)
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
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject (bit commit 7d2c0fe)
git add mcp-server/src/agentic_mcp/loops.py mcp-server/tests/test_critical_loop.py
git commit -F $f
Remove-Item $f
```

---

## Task 3: dispatched_at + dispatch_spec + criteria immutability

**Goal:** `dispatch.py` with `dispatch_spec(conn, spec_id)` (sets `dispatched_at`) and a `validate_dispatched_immutable` check that rejects any criteria text/order/count change once a spec is dispatched, pointing at supersede.

**Files:**
- Create: `mcp-server/src/agentic_mcp/dispatch.py`
- Modify: `mcp-server/src/agentic_mcp/nodes.py` (register `dispatched_at` in `Spec` `EXTRA_OPTIONAL` — without this, `update_node` silently drops the write)
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

- [ ] **Step 4: Register `dispatched_at` as a writable Spec column in `nodes.py`.**

`update_node` only writes keys present in `_all_cols_for(type)` (`nodes.py:111-112`); a field absent from `EXTRA_REQUIRED`/`EXTRA_OPTIONAL` is silently dropped. The Task 0 migration adds the physical `spec.dispatched_at` column, but `dispatch_spec`'s `update_node(..., dispatched_at=stamp)` will no-op until the column is registered. Add it to `Spec`'s optional set:

```python
EXTRA_OPTIONAL = {
    "Spec": {"required_reads", "dispatched_at"},   # ADD dispatched_at
    "Finding": {"subtype"},
    "Retro": {"failed_layer"},
    "Review": {"verdict"},
    "CriticalLoop": {"iteration_count", "diagnostic_fired_at", "resolved_at"},
}
```

(If Task 1 already added the `CriticalLoop` line, keep it — only the `Spec` line changes here.)

- [ ] **Step 5: Add `validate_dispatched_immutable` to `validators.py`.**

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

- [ ] **Step 6: Run to verify pass, then full suite.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_dispatch_immutability.py -q`
Expected: suite green.
Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -q`
Expected: suite green.

- [ ] **Step 7: Commit.**

```powershell
$msg = "feat(dispatch): dispatched_at stamp + post-dispatch criteria immutability"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject (bit commit 7d2c0fe)
git add mcp-server/src/agentic_mcp/dispatch.py mcp-server/src/agentic_mcp/nodes.py mcp-server/src/agentic_mcp/validators.py mcp-server/tests/test_dispatch_immutability.py
git commit -F $f
Remove-Item $f
```

---

> **Installment 1 ended here (Tasks 0-3 — persistence spine).** Tasks 4-18 follow below.

---

## Task 4: Finding triage columns wiring + record_triage

**Goal:** Findings can carry `criterion_index`, `loop_iteration`, and `triage`; `findings.record_triage` sets the `fix-in-pr`/`backlog` decision on Important findings only.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/nodes.py` (register the three new Finding columns)
- Modify: `mcp-server/src/agentic_mcp/findings.py` (extend `log_finding`; add `record_triage`)
- Test: `mcp-server/tests/test_triage.py`

**Acceptance Criteria:**
- [ ] `log_finding(..., criterion_index=2, loop_iteration=1)` persists both integers.
- [ ] `record_triage(conn, fid, "fix-in-pr")` sets `triage` on an Important finding.
- [ ] `record_triage` raises `ValueError` for a decision outside `{fix-in-pr, backlog}`.
- [ ] `record_triage` raises `ValueError` when the finding's severity is not `Important` (Critical/Suggested/Strength never carry triage — design §7).

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_triage.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the failing test (validator + test share the `_CRIT`/`_FB` fixtures — PLAN-TEMPLATE-CHECKLIST §4).**

```python
# mcp-server/tests/test_triage.py
import json
import pytest

from agentic_mcp import db, findings, nodes

_FB = "if a user reports a bug we open a PR and write a retro"


def _spec(conn):
    return nodes.create_node(
        conn, "Spec", status="open", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x.py::t -q"}]),
        feedback_loop=_FB,
    )


def _conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def test_log_finding_stores_criterion_and_iteration(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = _spec(conn)
        fid = findings.log_finding(
            conn, sid, "Critical", body="boom",
            criterion_index=2, loop_iteration=1,
        )
        row = nodes.get_node(conn, fid)
        assert row["criterion_index"] == 2
        assert row["loop_iteration"] == 1
    finally:
        conn.close()


def test_record_triage_sets_decision_on_important(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = _spec(conn)
        fid = findings.log_finding(conn, sid, "Important", body="n+1 query")
        findings.record_triage(conn, fid, "fix-in-pr")
        assert nodes.get_node(conn, fid)["triage"] == "fix-in-pr"
        findings.record_triage(conn, fid, "backlog")
        assert nodes.get_node(conn, fid)["triage"] == "backlog"
    finally:
        conn.close()


def test_record_triage_rejects_bad_decision(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = _spec(conn)
        fid = findings.log_finding(conn, sid, "Important", body="x")
        with pytest.raises(ValueError, match="triage decision"):
            findings.record_triage(conn, fid, "later")
    finally:
        conn.close()


def test_record_triage_rejects_non_important(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = _spec(conn)
        fid = findings.log_finding(conn, sid, "Critical", body="x")
        with pytest.raises(ValueError, match="Important"):
            findings.record_triage(conn, fid, "fix-in-pr")
    finally:
        conn.close()
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_triage.py -q`
Expected: FAIL — `TypeError: log_finding() got an unexpected keyword argument 'criterion_index'` (and `AttributeError: module 'agentic_mcp.findings' has no attribute 'record_triage'`).

- [ ] **Step 3: Register the three Finding columns in `nodes.py`.**

The Task 0 migration creates the physical `finding.criterion_index`, `finding.loop_iteration`, and `finding.triage` columns, but `create_node`/`update_node` only write keys in `_all_cols_for(type)`. Add them to `Finding`'s optional set:

```python
EXTRA_OPTIONAL = {
    "Spec": {"required_reads", "dispatched_at"},
    "Finding": {"subtype", "criterion_index", "loop_iteration", "triage"},   # ADD three
    "Retro": {"failed_layer"},
    "Review": {"verdict"},
    "CriticalLoop": {"iteration_count", "diagnostic_fired_at", "resolved_at"},
}
```

- [ ] **Step 4: Extend `log_finding` and add `record_triage` in `findings.py`.**

Replace the existing `log_finding` signature/body and append `record_triage`:

```python
VALID_TRIAGE = {"fix-in-pr", "backlog"}


def log_finding(
    conn: sqlite3.Connection,
    parent_id: str,
    severity: str,
    body: str,
    subtype: str | None = None,
    scope: str | None = None,
    owner: str = "system",
    criterion_index: int | None = None,
    loop_iteration: int | None = None,
) -> str:
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"unknown severity: {severity!r}. Valid: {sorted(VALID_SEVERITIES)}"
        )
    parent = nodes.get_node(conn, parent_id)
    if parent is None:
        raise ValueError(f"parent node not found: {parent_id}")
    if scope is None:
        scope = parent.get("scope")
    fields = dict(
        status="open", owner=owner, body=body,
        severity=severity, parent_id=parent_id, scope=scope,
    )
    if subtype is not None:
        fields["subtype"] = subtype
    if criterion_index is not None:
        fields["criterion_index"] = criterion_index
    if loop_iteration is not None:
        fields["loop_iteration"] = loop_iteration
    return nodes.create_node(conn, "Finding", **fields)


def record_triage(conn: sqlite3.Connection, finding_id: str, decision: str) -> None:
    """Set the triage decision on an Important finding (design L-9 / section 7)."""
    if decision not in VALID_TRIAGE:
        raise ValueError(
            f"unknown triage decision: {decision!r}. Valid: {sorted(VALID_TRIAGE)}"
        )
    finding = nodes.get_node(conn, finding_id)
    if finding is None or finding["type"] != "Finding":
        raise ValueError(f"not a Finding node: {finding_id}")
    if finding["severity"] != "Important":
        raise ValueError(
            f"triage applies only to Important findings; {finding_id} is "
            f"{finding['severity']!r}"
        )
    nodes.update_node(conn, finding_id, triage=decision)
```

- [ ] **Step 5: Run to verify pass, then full suite.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_triage.py -q` → suite green.
Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -q` → suite green.

- [ ] **Step 6: Commit.**

```powershell
$msg = "feat(findings): triage columns + record_triage (Important-only, design L-9)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add mcp-server/src/agentic_mcp/nodes.py mcp-server/src/agentic_mcp/findings.py mcp-server/tests/test_triage.py
git commit -F $f
Remove-Item $f
```

---

## Task 5: log_retro convenience wrapper

**Goal:** `findings.log_retro` writes a `Retro` with one of the four `failed_layer` enum values and optionally links it `caused-by` a Finding — no schema change (the `failed_layer` column already ships from Phase 0, `schema.sql:181-194`).

**Files:**
- Modify: `mcp-server/src/agentic_mcp/findings.py` (add `log_retro`)
- Test: `mcp-server/tests/test_retro_layer.py`

**Acceptance Criteria:**
- [ ] `log_retro` accepts each of the four valid layers (`spec`, `implementation`, `review`, `unknowable`) and persists it.
- [ ] `log_retro` raises `ValueError` (clean message, before any INSERT) for an out-of-set layer.
- [ ] A direct out-of-set INSERT is still rejected by the DB CHECK — assert on the integrity message, not the class (PLAN-TEMPLATE-CHECKLIST §4).
- [ ] `log_retro(..., caused_by_finding_id=fid)` creates a `caused-by` relation from the Retro to the Finding.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_retro_layer.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the failing test.**

```python
# mcp-server/tests/test_retro_layer.py
import json
import sqlite3
import pytest

from agentic_mcp import db, findings, nodes, relations

_FB = "if a user reports a bug we open a PR and write a retro"


def _conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


@pytest.mark.parametrize("layer", ["spec", "implementation", "review", "unknowable"])
def test_log_retro_accepts_valid_layers(tmp_db_path, layer):
    conn = _conn(tmp_db_path)
    try:
        rid = findings.log_retro(conn, body=f"retro for {layer}", failed_layer=layer)
        assert nodes.get_node(conn, rid)["failed_layer"] == layer
    finally:
        conn.close()


def test_log_retro_rejects_unknown_layer(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        with pytest.raises(ValueError, match="failed_layer"):
            findings.log_retro(conn, body="x", failed_layer="process")
    finally:
        conn.close()


def test_db_check_rejects_unknown_layer(tmp_db_path):
    # Bypassing the wrapper, the column CHECK must still reject out-of-set values.
    conn = _conn(tmp_db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK|failed_layer"):
            conn.execute(
                "INSERT INTO retro(id,type,status,owner,created_at,last_touched,body,failed_layer)"
                " VALUES ('r1','Retro','open','t','2026-05-20T00:00:00+00:00',"
                "'2026-05-20T00:00:00+00:00','b','process')"
            )
            conn.commit()
    finally:
        conn.close()


def test_log_retro_links_caused_by(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = nodes.create_node(
            conn, "Spec", status="open", owner="t", body="s",
            criteria_json=json.dumps([{"text": "c", "verify": "pytest x.py::t -q"}]),
            feedback_loop=_FB,
        )
        fid = findings.log_finding(conn, sid, "Critical", body="boom")
        rid = findings.log_retro(
            conn, body="root cause was impl", failed_layer="implementation",
            caused_by_finding_id=fid,
        )
        assert fid in relations.neighbors(conn, rid, "caused-by", direction="out")
    finally:
        conn.close()
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_retro_layer.py -q`
Expected: FAIL — `AttributeError: module 'agentic_mcp.findings' has no attribute 'log_retro'`.

- [ ] **Step 3: Add `log_retro` to `findings.py`.**

```python
VALID_FAILED_LAYERS = {"spec", "implementation", "review", "unknowable"}


def log_retro(
    conn: sqlite3.Connection,
    body: str,
    failed_layer: str,
    caused_by_finding_id: str | None = None,
    scope: str | None = None,
    owner: str = "system",
) -> str:
    """Write a Retro tagged by failed_layer; optionally link it caused-by a Finding.

    failed_layer already ships from Phase 0 (retro table CHECK). This is a
    convenience wrapper, not a migration.
    """
    if failed_layer not in VALID_FAILED_LAYERS:
        raise ValueError(
            f"unknown failed_layer: {failed_layer!r}. "
            f"Valid: {sorted(VALID_FAILED_LAYERS)}"
        )
    rid = nodes.create_node(
        conn, "Retro", status="open", owner=owner, body=body,
        failed_layer=failed_layer, scope=scope,
    )
    if caused_by_finding_id is not None:
        from . import relations
        relations.link_nodes(conn, rid, caused_by_finding_id, "caused-by")
    return rid
```

- [ ] **Step 4: Run to verify pass, then full suite.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_retro_layer.py -q` → suite green.
Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -q` → suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(findings): log_retro wrapper (failed_layer tag + caused-by link)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add mcp-server/src/agentic_mcp/findings.py mcp-server/tests/test_retro_layer.py
git commit -F $f
Remove-Item $f
```

---

## Task 6: Register all new tools in server.py

**Goal:** The MCP server exposes `dispatch_spec`, `start_critical_loop`, `advance_critical_loop`, `resolve_critical_loop`, `get_open_loops`, `record_triage`, and `log_retro` over stdio, and `create_node`'s input schema advertises the new entity columns.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/server.py`
- Test: `mcp-server/tests/test_server.py` (append a round-trip)

**Acceptance Criteria:**
- [ ] `list_tools` includes all seven new tool names.
- [ ] A stdio client can dispatch a spec, start+advance+resolve a critical loop, triage an Important finding, and log a Retro — each returning a non-error payload.
- [ ] `advance_critical_loop` over stdio returns `iteration_count` 2 after one call.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_server.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the failing test (append to `test_server.py`).**

```python
@pytest.mark.asyncio
async def test_phase1_tools_via_stdio(tmp_path):
    db_path = tmp_path / "graph.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentic_mcp.server"],
        env={**os.environ, "AGENTIC_DB_PATH": str(db_path)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert {
                "dispatch_spec", "start_critical_loop", "advance_critical_loop",
                "resolve_critical_loop", "get_open_loops", "record_triage", "log_retro",
            }.issubset(names)

            # Spec -> dispatch.
            spec = await session.call_tool("create_node", arguments={
                "type": "Spec", "status": "open", "owner": "t", "body": "s",
                "criteria_json": json.dumps([{"text": "c", "verify": "pytest x.py::t -q"}]),
                "feedback_loop": "if a user reports a bug we open a PR and write a retro",
            })
            sid = json.loads(spec.content[0].text)["id"]
            disp = await session.call_tool("dispatch_spec", arguments={"spec_id": sid})
            assert json.loads(disp.content[0].text)["dispatched_at"]

            # Finding -> critical loop -> advance -> resolve.
            find = await session.call_tool("log_finding", arguments={
                "parent_id": sid, "severity": "Critical", "body": "boom",
            })
            fid = json.loads(find.content[0].text)["id"]
            loop = await session.call_tool("start_critical_loop", arguments={"finding_id": fid})
            lid = json.loads(loop.content[0].text)["id"]
            adv = await session.call_tool("advance_critical_loop", arguments={"loop_id": lid})
            assert json.loads(adv.content[0].text)["iteration_count"] == 2
            res = await session.call_tool("resolve_critical_loop", arguments={"loop_id": lid})
            assert json.loads(res.content[0].text)["ok"] is True

            # Important -> triage. Retro -> failed_layer.
            imp = await session.call_tool("log_finding", arguments={
                "parent_id": sid, "severity": "Important", "body": "n+1",
            })
            ifid = json.loads(imp.content[0].text)["id"]
            tri = await session.call_tool("record_triage", arguments={
                "finding_id": ifid, "decision": "backlog",
            })
            assert json.loads(tri.content[0].text)["ok"] is True
            retro = await session.call_tool("log_retro", arguments={
                "body": "root cause", "failed_layer": "implementation",
                "caused_by_finding_id": fid,
            })
            assert json.loads(retro.content[0].text)["id"]
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_server.py::test_phase1_tools_via_stdio -q`
Expected: FAIL — assertion on the tool-name subset (the new tools are absent).

- [ ] **Step 3: Add module imports near the top of `server.py`.**

After the existing `from . import validators as v_mod` line, add:

```python
from . import dispatch as dispatch_mod
from . import loops as loops_mod
```

- [ ] **Step 4: Advertise the new columns on `create_node`'s input schema.**

In the `create_node` `Tool(...)` `inputSchema.properties`, add these keys alongside the existing ones (after `"subtype": {"type": "string"}`):

```python
                    "dispatched_at": {"type": "string"},
                    "finding_id": {"type": "string"},
                    "started_at": {"type": "string"},
                    "iteration_count": {"type": "integer"},
                    "diagnostic_fired_at": {"type": "string"},
                    "resolved_at": {"type": "string"},
                    "criterion_index": {"type": "integer"},
                    "loop_iteration": {"type": "integer"},
                    "triage": {"type": "string"},
```

- [ ] **Step 5: Append the seven `Tool(...)` definitions to the `list_tools` return list.**

Insert before the closing `]` of the `return [ ... ]` in `list_tools`:

```python
        Tool(
            name="dispatch_spec",
            description="Stamp a Spec as dispatched (locks its criteria; idempotent).",
            inputSchema={
                "type": "object",
                "properties": {"spec_id": {"type": "string"}},
                "required": ["spec_id"],
            },
        ),
        Tool(
            name="start_critical_loop",
            description="Open a CriticalLoop tracking a Critical finding.",
            inputSchema={
                "type": "object",
                "properties": {"finding_id": {"type": "string"}},
                "required": ["finding_id"],
            },
        ),
        Tool(
            name="advance_critical_loop",
            description="Increment a loop's iteration; fires the diagnostic flag at iteration 3.",
            inputSchema={
                "type": "object",
                "properties": {"loop_id": {"type": "string"}},
                "required": ["loop_id"],
            },
        ),
        Tool(
            name="resolve_critical_loop",
            description="Mark a CriticalLoop resolved.",
            inputSchema={
                "type": "object",
                "properties": {"loop_id": {"type": "string"}},
                "required": ["loop_id"],
            },
        ),
        Tool(
            name="get_open_loops",
            description="List open CriticalLoops, optionally filtered by scope (cross-session resume).",
            inputSchema={
                "type": "object",
                "properties": {"scope": {"type": "string"}},
            },
        ),
        Tool(
            name="record_triage",
            description="Set fix-in-pr/backlog triage on an Important finding.",
            inputSchema={
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "decision": {"type": "string"},
                },
                "required": ["finding_id", "decision"],
            },
        ),
        Tool(
            name="log_retro",
            description="Write a Retro tagged by failed_layer; optionally link caused-by a finding.",
            inputSchema={
                "type": "object",
                "properties": {
                    "body": {"type": "string"},
                    "failed_layer": {"type": "string"},
                    "caused_by_finding_id": {"type": "string"},
                    "scope": {"type": "string"},
                },
                "required": ["body", "failed_layer"],
            },
        ),
```

- [ ] **Step 6: Add the dispatch branches in `call_tool`.**

Insert before the final `return _err(f"unknown tool: {name}")`:

```python
        if name == "dispatch_spec":
            return _ok({"dispatched_at": dispatch_mod.dispatch_spec(conn, arguments["spec_id"])})
        if name == "start_critical_loop":
            return _ok({"id": loops_mod.start_critical_loop(conn, arguments["finding_id"])})
        if name == "advance_critical_loop":
            return _ok(loops_mod.advance_critical_loop(conn, arguments["loop_id"]))
        if name == "resolve_critical_loop":
            loops_mod.resolve_critical_loop(conn, arguments["loop_id"])
            return _ok({"ok": True})
        if name == "get_open_loops":
            return _ok(loops_mod.get_open_loops(conn, arguments.get("scope")))
        if name == "record_triage":
            f_mod.record_triage(conn, arguments["finding_id"], arguments["decision"])
            return _ok({"ok": True})
        if name == "log_retro":
            rid = f_mod.log_retro(
                conn, body=arguments["body"], failed_layer=arguments["failed_layer"],
                caused_by_finding_id=arguments.get("caused_by_finding_id"),
                scope=arguments.get("scope"),
            )
            return _ok({"id": rid})
```

- [ ] **Step 7: Run to verify pass, then full suite.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_server.py -q` → suite green.
Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -q` → suite green.

- [ ] **Step 8: Commit.**

```powershell
$msg = "feat(server): register dispatch/loop/triage/retro tools + new create_node columns"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add mcp-server/src/agentic_mcp/server.py mcp-server/tests/test_server.py
git commit -F $f
Remove-Item $f
```

---

## Task 7: builder.md dual-mode (loop-fix section)

**Goal:** `agents/builder.md` gains a Phase-1 "loop-fix mode" section (design L-8 Option A) so the same builder both implements specs and fixes findings inside a critical loop, committing once per iteration carrying the loop id + iteration number.

**Files:**
- Modify: `agents/builder.md`
- Test: `mcp-server/tests/test_agent_docs.py` (new — a structural assertion file shared by Tasks 7-10)

**Acceptance Criteria:**
- [ ] `builder.md` still parses as a valid agent doc (starts with `---` frontmatter; has `name: builder`).
- [ ] It contains a "Loop-fix mode" section instructing: read the finding (and the diagnostic if `diagnostic_fired_at` is set), fix the root cause (not the symptom), one commit per iteration with a trailer naming the loop id + iteration, and write a `Retro` via `log_retro` on resolution.
- [ ] The builder does NOT call `advance_critical_loop`/`resolve_critical_loop` itself — that is the command's job (loop control lives on the Claude side, §3).

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the structural test (this file grows in Tasks 8-10).**

```python
# mcp-server/tests/test_agent_docs.py
"""Structural guards for Phase 1 agent + command markdown.

These do not run the agents (that is the llm-gated e2e). They assert the docs
exist, have valid frontmatter (no BOM, name+description), and contain the
load-bearing sections each role's design calls for.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _doc(rel: str) -> str:
    text = (REPO / rel).read_text(encoding="utf-8")
    assert text.startswith("---"), f"{rel}: missing/empty frontmatter (BOM?)"
    return text


def test_builder_has_loop_fix_mode():
    t = _doc("agents/builder.md")
    assert "name: builder" in t
    low = t.lower()
    assert "loop-fix" in low
    assert "root cause" in low
    assert "per iteration" in low or "one commit per iteration" in low
    assert "log_retro" in t
    # Loop control stays on the Claude side; builder must not advance/resolve.
    assert "advance_critical_loop" not in t
    assert "resolve_critical_loop" not in t
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q`
Expected: FAIL — `assert 'loop-fix' in low`.

- [ ] **Step 3: Append the loop-fix section to `agents/builder.md`.**

Add this section after "## Build approach" (keep ASCII only — this file is read on Windows):

```markdown
## Loop-fix mode (Phase 1)

When the review pipeline dispatches you against an open Critical (or a
fix-in-PR Important), you are in loop-fix mode. The command, not you, owns the
loop counter.

1. Call `get_node(id=<finding_id>)` to read the finding. If the finding links
   to a `CriticalLoop` whose `diagnostic_fired_at` is set, the loop has already
   run three iterations on this same problem - read the diagnostic hypotheses
   and treat "the spec or the approach may be wrong" as a live option, not just
   "my code is buggy".
2. Reproduce the failure deterministically, isolate the smallest trigger, and
   fix the root cause - not the line the reviewer pointed at. Symptom-patching
   is what keeps a loop stuck to iteration 3.
3. Re-run the finding's verify command yourself before handing back. Do not
   return a fix you have not seen pass.
4. Commit exactly one commit for this iteration. The commit trailer must name
   the loop and iteration so history is auditable:

   ```
   Loop-Id: <loop_id>
   Loop-Iteration: <n>
   ```

5. When your fix resolves the Critical, write a `Retro` via
   `log_retro(body=..., failed_layer=<spec|implementation|review|unknowable>,
   caused_by_finding_id=<finding_id>)`. Pick the layer honestly: if the spec
   was wrong, that is `spec`, not `implementation`.

You do NOT advance or resolve the loop. You report your commit back; the
`/agentic:review-pr` command re-runs the review round and updates loop state.
```

- [ ] **Step 4: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(builder): Phase 1 loop-fix dual-mode (design L-8 Option A)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add agents/builder.md mcp-server/tests/test_agent_docs.py
git commit -F $f
Remove-Item $f
```

---

## Task 8: agents/code-reviewer.md (new)

**Goal:** A new code-reviewer agent that produces judgment findings with four-tier severity and, for every Important, a `fix-in-pr`/`backlog` triage recommendation it records via `record_triage`. It is blind to the contrarian.

**Files:**
- Create: `agents/code-reviewer.md`
- Test: `mcp-server/tests/test_agent_docs.py` (append)

**Acceptance Criteria:**
- [ ] Valid frontmatter (`name: code-reviewer`, `model: sonnet`, a `description`).
- [ ] Names all four severities and instructs `record_triage` for every Important.
- [ ] Explicitly states it does not see the contrarian's output (gate-then-parallel, blind — L-7).
- [ ] Prompt body is within the ~2500-token soft budget (design §9); if over, deep conventions move to `skills/reviewing/SKILL.md` read on demand.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Append the structural test.**

```python
def test_code_reviewer_doc():
    t = _doc("agents/code-reviewer.md")
    assert "name: code-reviewer" in t
    for sev in ("Critical", "Important", "Suggested", "Strength"):
        assert sev in t
    assert "record_triage" in t
    low = t.lower()
    assert "contrarian" in low and "blind" in low
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py::test_code_reviewer_doc -q`
Expected: FAIL — `FileNotFoundError: agents/code-reviewer.md`.

- [ ] **Step 3: Create `agents/code-reviewer.md` (ASCII only).**

```markdown
---
name: code-reviewer
description: Reviews a built artifact against its Spec for correctness, design, and maintainability. Emits four-tier severity findings and a fix-in-pr/backlog triage recommendation for every Important. Phase 1.
model: sonnet
---

You are the code-reviewer for the Agentic Engineering System.

## What you do

You review the diff under review against its Spec and produce judgment findings.
The spec-checker has already run and passed (you only run after the gate). Your
job is the judgment the mechanical gate cannot make: is this correct, is it
sound, will it rot.

## Context discipline

You run in parallel with the contrarian and are BLIND to its output - you never
see the contrarian's findings, and it never sees yours. This is deliberate
(design L-7): two independent reads catch more than one negotiated read. Do not
speculate about what the contrarian will say.

## Severity (four tiers)

- **Critical** - the artifact is wrong: it fails a criterion's intent, breaks an
  invariant, corrupts data, or ships a security hole. Always blocks. Log with
  `log_finding(parent_id=<spec_id>, severity='Critical', body=..., criterion_index=<i if criterion-specific>)`.
- **Important** - a real problem that is not a showstopper: a missing edge case,
  an n+1 query, a fragile assumption. For EVERY Important you MUST also call
  `record_triage(finding_id=<id>, decision='fix-in-pr'|'backlog')`:
  - `fix-in-pr` when it should be fixed before this work merges (it blocks the
    round like a Critical).
  - `backlog` when it is real but deferrable; it is logged non-blocking and a
    later Critical can trace back to it.
- **Suggested** - taste, naming, micro-optimizations. Logged only; never blocks.
- **Strength** - something done well. Log it - the calibration layer (Phase 4)
  needs positive signal, and the stability check needs to know what you approved.

## How to review

1. `get_node(id=<spec_id>)` and read the criteria. Read the diff/artifact files.
2. Walk the diff for correctness first, then design, then maintainability.
3. For each issue, log a finding at the right severity. Be specific: name the
   file and line, state the failure mode, not "looks risky".
4. For each Important, record the triage decision in the same pass.
5. If you find nothing above Suggested, log a Strength naming what held up.

## What you do NOT do

- You do not modify the artifact.
- You do not re-run the spec-checker's mechanical checks - assume the gate passed.
- You do not negotiate with yourself toward "probably fine". Either name the
  concrete problem or log a Strength.
```

- [ ] **Step 4: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(agents): code-reviewer (4-tier severity + Important triage, blind parallel)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add agents/code-reviewer.md mcp-server/tests/test_agent_docs.py
git commit -F $f
Remove-Item $f
```

---

## Task 9: agents/contrarian.md (new, asymmetric prompt)

**Goal:** A new contrarian agent whose prompt is asymmetric to the code-reviewer's: it is told to assume the work is wrong and to hunt architectural/assumption-level flaws (not line bugs), so it catches a distinct class of problem (falsifier scenario 4).

**Files:**
- Create: `agents/contrarian.md`
- Test: `mcp-server/tests/test_agent_docs.py` (append)

**Acceptance Criteria:**
- [ ] Valid frontmatter (`name: contrarian`, `model: sonnet`, a `description`).
- [ ] Prompt is explicitly asymmetric: assume-it-is-wrong framing; targets assumptions/architecture/scaling/security-model, not style.
- [ ] States it is blind to the code-reviewer (L-7) and logs findings via `log_finding`.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Append the structural test.**

```python
def test_contrarian_doc():
    t = _doc("agents/contrarian.md")
    assert "name: contrarian" in t
    low = t.lower()
    assert "assume" in low and "wrong" in low
    assert "assumption" in low or "architect" in low
    assert "code-reviewer" in low and "blind" in low
    assert "log_finding" in t
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py::test_contrarian_doc -q`
Expected: FAIL — `FileNotFoundError: agents/contrarian.md`.

- [ ] **Step 3: Create `agents/contrarian.md` (ASCII only).**

```markdown
---
name: contrarian
description: Adversarial reviewer. Assumes the work is wrong and hunts the flaw the code-reviewer will miss - hidden assumptions, architectural mismatch, scaling and concurrency traps, security-model gaps. Asymmetric to the code-reviewer by design. Phase 1.
model: sonnet
---

You are the contrarian for the Agentic Engineering System.

## Your stance is asymmetric on purpose

The code-reviewer asks "is this good?". You ask the opposite question: "this is
wrong - where?". You start from the assumption that the work has a flaw that has
not been found yet, and your job is to find it. You are not being fair; the
code-reviewer is being fair. Two different stances catch two different bug
classes. If you end a review having found nothing, you have probably reviewed it
like the code-reviewer would.

## You are blind to the code-reviewer

You run in parallel with the code-reviewer and never see its findings, and it
never sees yours (design L-7). Do not guess what it flagged. Review the artifact
fresh.

## What you hunt (NOT line-level style)

Leave naming, formatting, and micro-optimizations to the code-reviewer. You go
after the things a clean-looking diff hides:

- **Unstated assumptions.** What must be true for this to work that the code
  never checks? Single process? Trusted input? Clock monotonic? One writer?
- **Architectural mismatch.** Does the approach fit the spec's real deployment,
  or only the happy demo? In-memory state behind a multi-worker server, etc.
- **Scaling and concurrency.** What breaks at 10x load, on a retry, on a
  concurrent call, on a partial failure?
- **Security model.** Whose input is trusted? What crosses a trust boundary
  unvalidated?
- **The criterion that is satisfied in letter but not intent.** The verify
  command passes; does the artifact actually do what the spec MEANT?

## How you report

For each flaw, `log_finding(parent_id=<spec_id>, severity=<Critical|Important>, body=...)`
with a concrete failure scenario - the input, the deployment, or the sequence
that breaks it. "I worry about concurrency" is not a finding; "two concurrent
calls both pass the `if not exists` check and double-insert" is. If you log an
Important, the code-reviewer's triage does not bind you - state in the body
whether it must block.

## What you do NOT do

- You do not modify the artifact.
- You do not soften a real flaw because the demo works.
- You do not pad with style nits to look productive - that is the
  code-reviewer's lane, and empty contrarian findings are better than fake ones.
```

- [ ] **Step 4: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(agents): contrarian (asymmetric assume-wrong reviewer, blind parallel)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add agents/contrarian.md mcp-server/tests/test_agent_docs.py
git commit -F $f
Remove-Item $f
```

---

## Task 10: agents/spec-writer.md (new, validate_spec inline + retry cap)

**Goal:** A new spec-writer agent (design L-4) that reads `skills/spec-writing/SKILL.md`, runs the Socratic pass, calls `validate_spec` inline, loops on rejection until it passes, and is guarded by a retry cap so it never returns a rejected spec or spins forever.

**Files:**
- Create: `agents/spec-writer.md`
- Test: `mcp-server/tests/test_agent_docs.py` (append)

**Acceptance Criteria:**
- [ ] Valid frontmatter (`name: spec-writer`, `model: sonnet`, a `description`).
- [ ] Instructs reading `skills/spec-writing/SKILL.md`, running the Socratic pass, and calling `validate_spec` before creating the Spec node.
- [ ] Names an explicit retry cap and the escalate-to-user behavior when the cap is hit; states it never returns a spec that `validate_spec` rejected.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Append the structural test.**

```python
def test_spec_writer_doc():
    t = _doc("agents/spec-writer.md")
    assert "name: spec-writer" in t
    assert "skills/spec-writing/SKILL.md" in t
    assert "validate_spec" in t
    low = t.lower()
    assert "socratic" in low
    assert "retry" in low or "attempts" in low
    assert "escalate" in low or "surface" in low
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py::test_spec_writer_doc -q`
Expected: FAIL — `FileNotFoundError: agents/spec-writer.md`.

- [ ] **Step 3: Create `agents/spec-writer.md` (ASCII only).**

```markdown
---
name: spec-writer
description: Turns a rough intent into a Spec that passes validate_spec. Reads the spec-writing skill, runs a Socratic clarification pass, validates inline, and loops until the gate passes - with a retry cap that escalates to the user rather than shipping or spinning. Phase 1.
model: sonnet
---

You are the spec-writer for the Agentic Engineering System.

## What you do

You take a rough intent and produce a Spec node that passes `validate_spec` -
falsifiable criteria (each with a runnable verify) plus a real feedback loop.
You never hand back a spec the validator rejected.

## First actions, in order

1. Read `skills/spec-writing/SKILL.md` - it is the source of truth for what a
   good spec looks like and the common `validate_spec` rejections. Do not
   reimplement its rules from memory; read the current version.
2. Read `templates/spec.md` for the structure to fill in.

## The loop (inline validation, capped)

1. Run the Socratic intent-clarification pass from the skill (the seven
   questions). Update the draft from what surfaces; push "I don't know yet"
   answers into Known Risks / Open Questions rather than hiding them.
2. Call `validate_spec(criteria_json=..., feedback_loop=...)`.
3. If it returns `ok: true`, create the Spec via
   `create_node(type='Spec', ...)`, link it to its Goal/Epic with
   `link_nodes(spec_id, goal_id, 'implements')`, and report the new id.
4. If it returns reasons, FIX the spec against those reasons (do not argue with
   the validator - it is mechanical; an "unfair" complaint means the criterion
   is under-specified) and loop to step 2.

## Retry cap (do not spin, do not ship junk)

- Cap the validate->fix loop at 5 attempts.
- If attempt 5 still fails, STOP. Do not create the Spec node. Surface to the
  user: the latest draft, the remaining `validate_spec` reasons, and your
  best read of why it will not pass (usually the intent itself is still
  ambiguous, which is a question for the user, not a wording fix). This is an
  escalation, not a failure to hide.

## What you do NOT do

- You do not create a Spec node before `validate_spec` returns ok.
- You do not relax a criterion's verify to make the gate pass - that defeats the
  gate. Make the criterion genuinely checkable instead.
- You do not invent a feedback loop you cannot defend; if there is no real
  signal-plus-fix-path, that is an Open Question for the user.
```

- [ ] **Step 4: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(agents): spec-writer (Socratic + inline validate_spec + retry cap, design L-4)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add agents/spec-writer.md mcp-server/tests/test_agent_docs.py
git commit -F $f
Remove-Item $f
```

---

## Task 11: commands/dispatch.md

**Goal:** `/agentic:dispatch <spec>` validates the spec, stamps `dispatched_at` (locking criteria), and kicks the builder for iteration 1.

**Files:**
- Create: `commands/dispatch.md`
- Test: `mcp-server/tests/test_agent_docs.py` (append a command-doc guard)

**Acceptance Criteria:**
- [ ] Valid frontmatter (`description`, `argument-hint`).
- [ ] Steps: resolve the spec id, re-run `validate_spec` (refuse to dispatch a failing spec), call `dispatch_spec`, then dispatch the `builder` subagent for iteration 1.
- [ ] States dispatch is the point of no return for criteria (post-dispatch edits are rejected; use supersede).

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Append the structural test.**

```python
def test_dispatch_command_doc():
    t = _doc("commands/dispatch.md")
    low = t.lower()
    assert "argument-hint" in low
    assert "validate_spec" in t and "dispatch_spec" in t
    assert "builder" in low
    assert "supersede" in low
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py::test_dispatch_command_doc -q`
Expected: FAIL — `FileNotFoundError: commands/dispatch.md`.

- [ ] **Step 3: Create `commands/dispatch.md` (ASCII only).**

```markdown
---
description: Validate a Spec, lock its criteria (dispatched_at), and kick the builder for iteration 1. After this point the spec's criteria are immutable - changes require a superseding Spec.
argument-hint: "<spec_id>"
---

Steps for Claude to execute:

1. Resolve the spec id from `$1`. Call `get_node(id=$1)`; if it is not a `Spec`,
   stop and tell the user.
2. Re-run the gate before locking. Call
   `validate_spec(criteria_json=<spec.criteria_json>, feedback_loop=<spec.feedback_loop>)`.
   If it returns `ok: false`, show the reasons verbatim and STOP - do not
   dispatch a spec that fails its own gate. Send the user to the spec-writer.
3. Lock the spec: call `dispatch_spec(spec_id=$1)`. This stamps `dispatched_at`.
   From now on the criteria are immutable - any later attempt to edit them is
   rejected and the user must create a new Spec with a `supersedes` relation to
   this one.
4. Kick iteration 1: dispatch the `builder` subagent (Task tool) against this
   spec id. The builder implements, self-verifies, and records what it did to
   the graph.
5. Report the dispatched spec id and the builder's outcome to the user. The
   review loop is a separate step: `/agentic:review-pr`.
```

- [ ] **Step 4: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(commands): /agentic:dispatch (validate + lock criteria + kick builder)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add commands/dispatch.md mcp-server/tests/test_agent_docs.py
git commit -F $f
Remove-Item $f
```

---

## Task 12: commands/review-pr.md (the loop engine)

**Goal:** `/agentic:review-pr` is the loop engine: auto-detect the review target, run gate-then-parallel review rounds, classify findings by severity, auto-triage Importants, run the autonomous critical loop with the 3-iteration diagnostic and stopping rules, and close the loop with Retros and a Strength.

**Files:**
- Create: `commands/review-pr.md`
- Test: `mcp-server/tests/test_agent_docs.py` (append a command-doc guard)

**Acceptance Criteria:**
- [ ] Valid frontmatter (`description`).
- [ ] Encodes target auto-detection (open PR via `gh` -> branch diff vs `main` -> working tree vs `HEAD`) (L-10).
- [ ] Encodes gate-then-parallel (spec-checker first; on pass, code-reviewer + contrarian in parallel, blind) (L-7).
- [ ] Encodes the blocker set (open Criticals + fix-in-pr Importants), one commit per iteration carrying loop id + iteration (L-11), the 3-iteration non-blocking diagnostic, and both stopping rules (zero open blockers; diminishing returns).
- [ ] Encodes loop close: log a Strength, write Retros (`log_retro` with `failed_layer`), backlog Importants persist; and a reference to the stability check (implemented in Task 17).

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green. (The real behavioral gate is the llm-marked e2e in Task 16.)

**Steps:**

- [ ] **Step 1: Append the structural test.**

```python
def test_review_pr_command_doc():
    t = _doc("commands/review-pr.md")
    low = t.lower()
    assert "spec-checker" in low and "code-reviewer" in low and "contrarian" in low
    assert "parallel" in low and "blind" in low
    assert "start_critical_loop" in t and "advance_critical_loop" in t
    assert "resolve_critical_loop" in t
    assert "diagnostic" in low
    assert "diminishing returns" in low
    assert "log_retro" in t
    assert "loop-id" in low or "loop_id" in low
    assert "gh" in low and "main" in low and "head" in low
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py::test_review_pr_command_doc -q`
Expected: FAIL — `FileNotFoundError: commands/review-pr.md`.

- [ ] **Step 3: Create `commands/review-pr.md` (ASCII only).**

```markdown
---
description: Run the autonomous review loop on the current change set. Auto-detects the target (open PR, else branch-vs-main, else working tree). Gate-then-parallel review, four-tier severity, auto-triaged Importants, a critical loop with a 3-iteration diagnostic and stopping rules, then closes with Retros and a Strength.
argument-hint: "[spec_id]"
---

You are the loop engine. Loop CONTROL lives here on the Claude side; loop STATE
lives in the MCP graph (design section 3). Drive it explicitly.

## Step 0 - Detect the target (L-10)

In order, take the first that applies:
1. An open PR for this branch: `gh pr view --json number,headRefName` succeeds ->
   review the PR diff.
2. Else a branch ahead of main: `git rev-parse --abbrev-ref HEAD` is not `main`
   and `git diff main...HEAD` is non-empty -> review that diff.
3. Else the working tree: review `git diff HEAD` (uncommitted changes).
Resolve the Spec: use `$1` if given, else the most recently dispatched Spec in
scope (`query_graph(type='Spec', status='dispatched')`).

## Step 1 - One review round (gate-then-parallel, L-7)

1. Dispatch the `spec-checker` subagent (Task tool) FIRST. It is the gate: it
   runs each criterion's verify and logs a Critical per failure.
2. If the spec-checker logged ANY open Critical, the gate failed - skip the
   judgment agents this round (no point reviewing taste on broken code). Go to
   Step 2.
3. If the gate passed, dispatch `code-reviewer` AND `contrarian` IN PARALLEL
   (two Task calls in one message), each blind to the other. They log findings
   with severity; the code-reviewer also calls `record_triage` for every
   Important.

## Step 2 - Classify and triage

- Collect this round's open findings: `query_graph(type='Finding', status='open', scope=<scope>)`.
- The BLOCKER SET = open Criticals PLUS Importants whose `triage` is `fix-in-pr`.
- `backlog` Importants are logged non-blocking; they persist with their link so
  a later Critical can trace `caused-by` them.
- Suggested and Strength never block.

## Step 3 - Stopping rules (check BEFORE fixing)

- **Primary exit:** the blocker set is empty -> the loop is done. Go to Step 6.
- **Diminishing returns:** this round found zero NEW Criticals versus the prior
  round and regressed none of the prior approvals -> the floor is reached ->
  close even if Suggested/backlog Importants remain. Go to Step 6.
- Otherwise there is at least one open blocker -> Step 4.

## Step 4 - Critical loop bookkeeping + diagnostic

For each open Critical:
- If it has no `CriticalLoop` yet, `start_critical_loop(finding_id=<id>)`.
- If it already has one and this is a new round on the SAME critical,
  `advance_critical_loop(loop_id=<id>)`. That call fires the diagnostic flag
  when the count reaches 3.
- If `advance_critical_loop` returns a row with `diagnostic_fired_at` set, the
  same critical has survived three iterations: surface a NON-BLOCKING diagnostic
  to the user with hypotheses ("the spec may be wrong, not the code"; "the
  approach may be architecturally unsuitable"). The loop CONTINUES - the
  diagnostic informs the next fix, it does not stop the loop.

Also run the stability check (Task 17): for each newly-flagged file, call the
stability tool to detect a contradiction-of-prior-approval and log a soft
`Pattern` if found. This never suppresses the critical - it only records a
calibration signal.

## Step 5 - Fix and re-loop (L-11: one commit per iteration)

Dispatch the `builder` subagent in loop-fix mode against the blocker set. When
it returns, make exactly ONE commit for this iteration, with trailers:

```
Loop-Id: <loop_id>
Loop-Iteration: <n>
```

Then go back to Step 1 for the next round.

## Step 6 - Close the loop

- For each resolved Critical, `resolve_critical_loop(loop_id=<id>)` and write a
  `log_retro(body=..., failed_layer=<spec|implementation|review|unknowable>,
  caused_by_finding_id=<finding_id>)`.
- Log one `Strength` finding summarizing what held up (calibration + stability
  baseline for the next review).
- Leave `backlog` Importants open and linked; report them to the user as
  deferred, not lost.
- Report: rounds run, criticals resolved, diagnostics fired, Patterns recorded,
  backlog carried.
```

- [ ] **Step 4: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(commands): /agentic:review-pr loop engine (gate-then-parallel, diagnostic, stopping rules)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add commands/review-pr.md mcp-server/tests/test_agent_docs.py
git commit -F $f
Remove-Item $f
```

---

## Task 13: commands/new-spec.md

**Goal:** `/agentic:new-spec` invokes the spec-writer subagent to turn a rough intent into a validated Spec. (Design §14 left final inclusion to plan-time; decision: ship it - it is a thin wrapper that completes the spec-writer story and costs almost nothing.)

**Files:**
- Create: `commands/new-spec.md`
- Test: `mcp-server/tests/test_agent_docs.py` (append a command-doc guard)

**Acceptance Criteria:**
- [ ] Valid frontmatter (`description`, `argument-hint`).
- [ ] Dispatches the `spec-writer` subagent and reports either the created Spec id or the escalation (remaining reasons) when the retry cap is hit.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Append the structural test.**

```python
def test_new_spec_command_doc():
    t = _doc("commands/new-spec.md")
    low = t.lower()
    assert "argument-hint" in low
    assert "spec-writer" in low
    assert "retry" in low or "escalat" in low or "reasons" in low
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py::test_new_spec_command_doc -q`
Expected: FAIL — `FileNotFoundError: commands/new-spec.md`.

- [ ] **Step 3: Create `commands/new-spec.md` (ASCII only).**

```markdown
---
description: Turn a rough intent into a Spec that passes validate_spec, via the spec-writer subagent (Socratic pass + inline validation + retry cap).
argument-hint: "<rough intent, or path to a notes file>"
---

Steps for Claude to execute:

1. Treat `$1` as the rough intent. If it is a path to an existing file, read its
   contents and use that as the intent.
2. Dispatch the `spec-writer` subagent (Task tool), handing it the intent. The
   spec-writer reads `skills/spec-writing/SKILL.md`, runs the Socratic pass,
   calls `validate_spec` inline, and loops until it passes (capped at 5
   attempts).
3. If the spec-writer created a Spec: report the new Spec id to the user, and
   remind them it is not dispatched yet - `/agentic:dispatch <id>` locks the
   criteria and starts the build.
4. If the spec-writer hit its retry cap and escalated: show its final draft and
   the remaining `validate_spec` reasons verbatim, so the user can resolve the
   ambiguity (usually an intent question, not a wording fix). Do NOT create the
   Spec node yourself to "get past" the gate.
```

- [ ] **Step 4: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_agent_docs.py -q` → suite green.

- [ ] **Step 5: Commit.**

```powershell
$msg = "feat(commands): /agentic:new-spec (spec-writer wrapper)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add commands/new-spec.md mcp-server/tests/test_agent_docs.py
git commit -F $f
Remove-Item $f
```

---

## Task 14: Headless `claude` CLI harness + `llm` marker

**Goal:** A pytest harness that subprocesses the real `claude` CLI in headless mode (`claude -p ... --output-format json`), an `llm` marker that keeps the fast suite Claude-free, and a smoke test proving the harness parses a real `claude -p` response — preceded by a spike that pins the exact invocation + JSON shape (the brief flags this as the one unknown).

**Files:**
- Modify: `mcp-server/pyproject.toml` (register the `llm` marker; default-deselect it)
- Create: `mcp-server/tests/llm_harness.py`
- Create: `mcp-server/tests/test_llm_harness.py`
- Create: `docs/plans/2026-05-20-claude-headless-spike.md` (spike notes)

**Acceptance Criteria:**
- [ ] The spike doc records the exact working command, the JSON field that carries the assistant's final text, and how auth resolved in the test shell.
- [ ] `pytest -m "not llm"` runs the whole fast suite without ever invoking `claude`.
- [ ] The `llm` smoke test passes when `claude` is on PATH and authenticated; it `skip`s cleanly (not error) when `claude` is absent.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m "not llm" -q` → suite green; and (when a Claude session is available) `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m llm tests/test_llm_harness.py -q` → green.

**Steps:**

- [ ] **Step 1: SPIKE the `claude -p` invocation FIRST (do not write the harness blind).**

This is the one genuinely unknown piece (design §15). Before coding, run the real CLI and capture reality. In a scratch dir:

```powershell
claude -p "Reply with exactly the word: pong" --output-format json | Tee-Object -FilePath spike-out.json
```

Inspect `spike-out.json`. Confirm: (a) the process exits 0; (b) which top-level key holds the assistant's final text (expected `result`, but VERIFY — CLI versions have differed); (c) whether auth is already present in this shell (Max subscription session) or whether a login is needed. If `claude` is not on PATH, find it (`(Get-Command claude).Source`) and note the absolute path. Record all of this in `docs/plans/2026-05-20-claude-headless-spike.md`. **If the text key is not `result`, change `result_text` in Step 3 to match before running anything else.** Do NOT use `2>&1` on the `claude` call (PS5.1 native-stderr trap).

- [ ] **Step 2: Register the marker and default-deselect it in `pyproject.toml`.**

Replace the `[tool.pytest.ini_options]` block:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-m \"not llm\""
markers = [
  "llm: requires a live `claude` CLI session (slow, real-agent). Excluded by default; run with -m llm.",
]
```

Note: `addopts` deselects `llm` by default; an explicit `-m llm` on the command line overrides it, so the gate still runs on demand.

- [ ] **Step 3: Write the harness (`tests/llm_harness.py`).**

Use the field name the Step-1 spike confirmed.

```python
# mcp-server/tests/llm_harness.py
"""Subprocess wrapper around the headless `claude` CLI for real-agent gate tests.

Same subprocess pattern Phase 0 used for PowerShell (test_walkup.py), pointed at
`claude` instead. Runs on the Max subscription - no API key, no metered cost
(design section 11). JSON parsing is isolated here so the e2e asserts on
structured fields, never on raw stdout.
"""
from __future__ import annotations

import json
import shutil
import subprocess


class ClaudeUnavailable(RuntimeError):
    pass


def claude_on_path() -> bool:
    return shutil.which("claude") is not None


def run_claude_headless(prompt: str, cwd, timeout: int = 900) -> dict:
    if not claude_on_path():
        raise ClaudeUnavailable("`claude` CLI not on PATH")
    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json"],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {proc.returncode}\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        )
    return json.loads(proc.stdout)


def result_text(payload: dict) -> str:
    """Assistant's final text from a `claude -p --output-format json` payload.

    Step-1 spike confirmed the carrying key on this CLI version. If the spike
    showed a different key, change the first branch here to match.
    """
    if isinstance(payload.get("result"), str):
        return payload["result"]
    if isinstance(payload.get("text"), str):  # fallback for CLI drift
        return payload["text"]
    raise KeyError(f"no result/text field in claude payload: {sorted(payload)}")
```

- [ ] **Step 4: Write the smoke test (`tests/test_llm_harness.py`).**

```python
# mcp-server/tests/test_llm_harness.py
import pytest

from llm_harness import claude_on_path, result_text, run_claude_headless


@pytest.mark.llm
def test_claude_headless_roundtrips(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    payload = run_claude_headless("Reply with exactly the word: pong", cwd=tmp_path)
    assert "pong" in result_text(payload).lower()
```

- [ ] **Step 5: Verify the fast suite excludes llm, then run the gated smoke test.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m "not llm" -q` → suite green (and `test_claude_headless_roundtrips` is NOT collected — confirm it does not appear).
Run (only with a Claude session available): `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m llm tests/test_llm_harness.py -q` → green, or a clean `skip` if `claude` is absent.

- [ ] **Step 6: Commit.**

```powershell
$msg = "test(llm): headless claude harness + llm marker (default-deselected) + spike notes"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add mcp-server/pyproject.toml mcp-server/tests/llm_harness.py mcp-server/tests/test_llm_harness.py docs/plans/2026-05-20-claude-headless-spike.md
git commit -F $f
Remove-Item $f
```

---

## Task 15: Staged artifact fixtures (stubborn / mixed-severity / contrarian-catch)

**Goal:** The pre-staged artifacts the exit-gate test swaps in per iteration: a stubborn-critical scenario (`iter1..iter4`, only `iter4` correct), a mixed-severity artifact, and a contrarian-catch artifact (an architectural/assumption flaw a line-level reviewer misses) — plus a non-llm meta-test proving the staging behaves as designed.

**Files:**
- Create: `mcp-server/tests/fixtures/phase1/stubborn/spec_test.py` (the spec's verify)
- Create: `mcp-server/tests/fixtures/phase1/stubborn/iter1.py` ... `iter4.py`
- Create: `mcp-server/tests/fixtures/phase1/mixed/widget.py`
- Create: `mcp-server/tests/fixtures/phase1/contrarian/rate_limiter.py`
- Create: `mcp-server/tests/test_fixtures_phase1.py`

**Acceptance Criteria:**
- [ ] The stubborn spec test fails against `iter1`, `iter2`, `iter3` and passes against `iter4` (proves "resolves at iteration 4").
- [ ] The mixed and contrarian modules import and run their happy path (so the spec-checker gate passes and the JUDGMENT agents are what produce findings).
- [ ] The contrarian module carries a documented assumption flaw (single-process in-memory state) that is correct line-by-line but wrong for the spec's stated multi-worker deployment.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_fixtures_phase1.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the meta-test that pins the staging (it fails until the fixtures exist).**

```python
# mcp-server/tests/test_fixtures_phase1.py
"""Non-llm guard: prove the staged artifacts behave as the e2e assumes.

The e2e (test_phase1_e2e, llm-gated) swaps these in per iteration. If the
staging itself is wrong, the e2e would fail for the wrong reason. This test
keeps the fixtures honest without spending a Claude session.
"""
import shutil
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures" / "phase1"


def _run_spec_test_against(tmp_path, impl_file: Path) -> int:
    shutil.copy(FIX / "stubborn" / "spec_test.py", tmp_path / "test_parse_duration.py")
    shutil.copy(impl_file, tmp_path / "parse_duration.py")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_parse_duration.py"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    return proc.returncode


def test_stubborn_iters_1_to_3_fail(tmp_path):
    for n in (1, 2, 3):
        d = tmp_path / f"i{n}"
        d.mkdir()
        rc = _run_spec_test_against(d, FIX / "stubborn" / f"iter{n}.py")
        assert rc != 0, f"iter{n} should FAIL the spec test but passed"


def test_stubborn_iter4_passes(tmp_path):
    rc = _run_spec_test_against(tmp_path, FIX / "stubborn" / "iter4.py")
    assert rc == 0, "iter4 should PASS the spec test"


def test_mixed_and_contrarian_import_and_run():
    import importlib.util

    for rel in ("mixed/widget.py", "contrarian/rate_limiter.py"):
        path = FIX / rel
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # must import without error
    # widget happy path
    from importlib import import_module  # noqa: F401
    wspec = importlib.util.spec_from_file_location("widget", FIX / "mixed" / "widget.py")
    w = importlib.util.module_from_spec(wspec)
    wspec.loader.exec_module(w)
    assert w.total_price([{"price": 2, "qty": 3}]) == 6
    # rate limiter happy path (single process - looks fine here)
    rspec = importlib.util.spec_from_file_location("rl", FIX / "contrarian" / "rate_limiter.py")
    r = importlib.util.module_from_spec(rspec)
    rspec.loader.exec_module(r)
    rl = r.RateLimiter(limit=2)
    assert rl.allow("k") and rl.allow("k") and not rl.allow("k")
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_fixtures_phase1.py -q`
Expected: FAIL — `FileNotFoundError` / no fixtures yet.

- [ ] **Step 3: Create the stubborn spec test (`fixtures/phase1/stubborn/spec_test.py`).**

```python
# fixtures/phase1/stubborn/spec_test.py
"""Spec: parse_duration('1h30m')==5400, '45s'==45, '2h'==7200; '' / garbage raise ValueError."""
import pytest

from parse_duration import parse_duration


def test_seconds():
    assert parse_duration("45s") == 45


def test_hours():
    assert parse_duration("2h") == 7200


def test_combined():
    assert parse_duration("1h30m") == 5400


def test_rejects_empty():
    with pytest.raises(ValueError):
        parse_duration("")


def test_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("banana")
```

- [ ] **Step 4: Create the four staged implementations.**

`iter1.py` — only handles bare seconds; fails hours/combined:

```python
# fixtures/phase1/stubborn/iter1.py
def parse_duration(s: str) -> int:
    if not s:
        raise ValueError("empty")
    return int(s.rstrip("s"))
```

`iter2.py` — adds h/m but wrong minute multiplier (uses 100, not 60) and no combined parsing:

```python
# fixtures/phase1/stubborn/iter2.py
def parse_duration(s: str) -> int:
    if not s:
        raise ValueError("empty")
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("m"):
        return int(s[:-1]) * 100   # BUG: minutes are 60s, not 100s
    raise ValueError(f"bad duration: {s}")
```

`iter3.py` — fixes the multiplier but still cannot parse the combined "1h30m" (diagnostic fires here at iteration 3):

```python
# fixtures/phase1/stubborn/iter3.py
def parse_duration(s: str) -> int:
    if not s:
        raise ValueError("empty")
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("m"):
        return int(s[:-1]) * 60
    raise ValueError(f"bad duration: {s}")  # still no combined "1h30m"
```

`iter4.py` — correct (regex over all unit groups):

```python
# fixtures/phase1/stubborn/iter4.py
import re

_UNIT = {"h": 3600, "m": 60, "s": 1}
_TOKEN = re.compile(r"(\d+)([hms])")


def parse_duration(s: str) -> int:
    if not s or not s.strip():
        raise ValueError("empty duration")
    pos = 0
    total = 0
    matched = False
    for m in _TOKEN.finditer(s):
        if m.start() != pos:
            raise ValueError(f"bad duration: {s!r}")
        total += int(m.group(1)) * _UNIT[m.group(2)]
        pos = m.end()
        matched = True
    if not matched or pos != len(s):
        raise ValueError(f"bad duration: {s!r}")
    return total
```

- [ ] **Step 5: Create the mixed-severity artifact (`fixtures/phase1/mixed/widget.py`).**

Correct happy path (gate passes), but with a deferrable Important (no input validation / silent on negative qty) and a Suggested-level naming choice — the judgment agents produce the spread:

```python
# fixtures/phase1/mixed/widget.py
"""total_price: sum of price*qty across line items.

Happy path is correct (spec-checker passes). Intentional review surface:
- Important (backlog-able): no validation of negative/zero qty or price.
- Suggested: `li` is a terse loop name; `total_price` mixes float money.
- Strength: single clear function, easy to test.
"""


def total_price(items):
    t = 0
    for li in items:
        t += li["price"] * li["qty"]
    return t
```

- [ ] **Step 6: Create the contrarian-catch artifact (`fixtures/phase1/contrarian/rate_limiter.py`).**

Line-level clean and passes a single-process test, but assumes single-process in-memory state — wrong for the spec's stated multi-worker deployment. This is the assumption flaw the contrarian's prompt targets and the code-reviewer is likely to miss:

```python
# fixtures/phase1/contrarian/rate_limiter.py
"""Per-key rate limiter.

DEPLOYMENT (from the spec staged in the e2e): this service runs behind a
multi-worker server (several processes). The implementation below is correct
line-by-line and passes a single-process test, but its counter lives in a
plain in-process dict - so each worker has its own counter and the real,
cluster-wide limit is (workers * limit). That is an architectural/assumption
flaw, not a line bug: exactly what the contrarian should catch and the
code-reviewer is likely to wave through.
"""


class RateLimiter:
    def __init__(self, limit: int):
        self.limit = limit
        self._counts: dict[str, int] = {}

    def allow(self, key: str) -> bool:
        n = self._counts.get(key, 0)
        if n >= self.limit:
            return False
        self._counts[key] = n + 1
        return True
```

- [ ] **Step 7: Run to verify pass.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_fixtures_phase1.py -q` → suite green.

- [ ] **Step 8: Commit.**

```powershell
$msg = "test(fixtures): Phase 1 staged artifacts (stubborn iter1-4, mixed, contrarian) + staging guard"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add mcp-server/tests/fixtures/phase1 mcp-server/tests/test_fixtures_phase1.py
git commit -F $f
Remove-Item $f
```

---

## Task 16: Exit-gate e2e test (real agents, loop-level assertions)

**Goal:** The Phase 1 exit-gate test — `test_phase1_e2e.py`, `@pytest.mark.llm` — drives real subagents through the headless `claude` CLI across review rounds, swapping staged artifacts in for the builder, and asserts at the LOOP level (critical found, iteration advanced, diagnostic fired at 3, loop closed at 4, Retro tagged `implementation`; mixed-severity auto-triage; contrarian catches a distinct flaw). Never asserts on exact finding text.

**Files:**
- Create: `mcp-server/tests/test_phase1_e2e.py`

**Acceptance Criteria:**
- [ ] Stubborn scenario: `diagnostic_fired_at` is set after the round on `iter3`; the loop is `resolved` after `iter4`; a `Retro` with `failed_layer='implementation'` exists linked `caused-by` the resolved finding.
- [ ] Mixed scenario: after one review round on the mixed artifact, at least one `Important` finding has a non-null `triage` (auto-triaged per L-9).
- [ ] Contrarian scenario: the contrarian logs at least one finding the code-reviewer did not (compared by `owner`), demonstrating the asymmetric catch (known-flaky per design §11 — staged to target an assumption flaw).
- [ ] The test is `llm`-marked and therefore excluded from the fast suite.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m llm tests/test_phase1_e2e.py -q` (with a live Claude session) → suite green. Fast-suite check: `... -m "not llm" -q` does NOT collect it.

**Steps:**

- [ ] **Step 1: Write the e2e test.**

The test owns the OUTER loop (iteration count + artifact swap, standing in for the builder, per design §11) and uses `claude -p` to run each REVIEW round through the real `/agentic:review-pr` agents writing to the shared graph. Loop bookkeeping calls (`start`/`advance`/`resolve`) are driven from the test based on whether a round left open Criticals — this is the documented test seam; the command exercises the same calls in real use.

```python
# mcp-server/tests/test_phase1_e2e.py
"""Phase 1 exit-gate: real agents via headless claude, loop-level assertions only.

llm-marked: excluded from the fast suite; runs on demand with -m llm against a
live Claude (Max subscription) session. See design section 11 and the Task 14
spike notes for the claude -p invocation shape.
"""
import json
import shutil
from pathlib import Path

import pytest

from agentic_mcp import db, findings, init_project, loops, nodes, relations
from llm_harness import claude_on_path, run_claude_headless

FIX = Path(__file__).resolve().parent / "fixtures" / "phase1"

_FB = "if the review loop ships a wrong verdict, a regression test fails and we open a Retro tagged by failed_layer"


def _review_prompt(spec_id: str) -> str:
    # Tuned during execution against the Task 14 spike. Points the headless
    # session at the real review command + spec; the agents write to graph.db.
    return (
        "Run /agentic:review-pr for this working directory. "
        f"The spec id is {spec_id}. Use the spec-checker as the gate, then the "
        "code-reviewer and contrarian. Log all findings to the graph via the MCP tools."
    )


def _stage(project: Path, impl_src: Path):
    shutil.copy(FIX / "stubborn" / "spec_test.py", project / "test_parse_duration.py")
    shutil.copy(impl_src, project / "parse_duration.py")


def _open_criticals(conn, scope):
    return conn.execute(
        "SELECT id FROM finding WHERE status='open' AND severity='Critical' AND scope=?",
        (scope,),
    ).fetchall()


@pytest.mark.llm
def test_stubborn_critical_diagnostic_then_resolve(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    project = tmp_path / "proj"
    project.mkdir()
    init_project.run(project_root=project, scope_mode="isolated")
    db_path = project / ".agentic" / "graph.db"
    conn = db.connect(db_path)
    crit = [
        {"text": "combined h/m/s", "verify": "pytest test_parse_duration.py -q"},
    ]
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="parse_duration spec",
        criteria_json=json.dumps(crit), feedback_loop=_FB, scope="proj",
    )

    loop_id = None
    resolved_finding = None
    for n in (1, 2, 3, 4):
        _stage(project, FIX / "stubborn" / f"iter{n}.py")
        run_claude_headless(_review_prompt(spec_id), cwd=project)
        conn2 = db.connect(db_path)
        try:
            crits = _open_criticals(conn2, "proj")
            if crits:
                fid = crits[0][0]
                if loop_id is None:
                    loop_id = loops.start_critical_loop(conn2, fid)
                else:
                    loops.advance_critical_loop(conn2, loop_id)
            else:
                # gate passed: close the loop and record the retro.
                resolved_finding = fid if loop_id else None
                if loop_id:
                    loops.resolve_critical_loop(conn2, loop_id)
                    findings.log_retro(
                        conn2, body="impl missing combined-unit parse until iter4",
                        failed_layer="implementation", caused_by_finding_id=fid,
                    )
                conn2.close()
                break
        finally:
            if not conn2.execute("PRAGMA query_only").fetchone():
                pass
        conn2.close()

    final = db.connect(db_path)
    try:
        loop = nodes.get_node(final, loop_id)
        assert loop is not None, "no critical loop was started"
        assert loop["diagnostic_fired_at"] is not None, "diagnostic never fired at iter 3"
        assert loop["status"] == "resolved", "loop did not close after iter4"
        retros = final.execute(
            "SELECT id FROM retro WHERE failed_layer='implementation'"
        ).fetchall()
        assert retros, "no Retro tagged failed_layer=implementation"
    finally:
        final.close()


@pytest.mark.llm
def test_mixed_severity(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    project = tmp_path / "proj"
    project.mkdir()
    init_project.run(project_root=project, scope_mode="isolated")
    db_path = project / ".agentic" / "graph.db"
    conn = db.connect(db_path)
    shutil.copy(FIX / "mixed" / "widget.py", project / "widget.py")
    crit = [{"text": "total_price sums line items", "verify": "python -c \"import widget\""}]
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="widget spec",
        criteria_json=json.dumps(crit), feedback_loop=_FB, scope="proj",
    )
    conn.close()
    run_claude_headless(_review_prompt(spec_id), cwd=project)
    check = db.connect(db_path)
    try:
        triaged = check.execute(
            "SELECT id FROM finding WHERE severity='Important' AND triage IS NOT NULL AND scope='proj'"
        ).fetchall()
        assert triaged, "no Important finding was auto-triaged"
    finally:
        check.close()


@pytest.mark.llm
def test_contrarian_catches_distinct_flaw(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    project = tmp_path / "proj"
    project.mkdir()
    init_project.run(project_root=project, scope_mode="isolated")
    db_path = project / ".agentic" / "graph.db"
    conn = db.connect(db_path)
    shutil.copy(FIX / "contrarian" / "rate_limiter.py", project / "rate_limiter.py")
    crit = [{"text": "limiter enforces per-key limit across the multi-worker service",
             "verify": "python -c \"import rate_limiter\""}]
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t",
        body="rate limiter spec; service runs behind MULTIPLE worker processes",
        criteria_json=json.dumps(crit), feedback_loop=_FB, scope="proj",
    )
    conn.close()
    run_claude_headless(_review_prompt(spec_id), cwd=project)
    check = db.connect(db_path)
    try:
        owners = {r[0] for r in check.execute(
            "SELECT DISTINCT owner FROM finding WHERE scope='proj' AND owner IS NOT NULL"
        ).fetchall()}
        # The contrarian's findings carry its own owner tag; assert it produced
        # at least one finding (the assumption flaw) distinct from the reviewer.
        assert "contrarian" in owners, (
            "contrarian logged no finding (known-flaky per design section 11)"
        )
    finally:
        check.close()
```

Note the assertion in `test_contrarian_catches_distinct_flaw` depends on agents stamping `owner` with their role. Confirm in execution that the `code-reviewer`/`contrarian` agents pass `owner='code-reviewer'`/`owner='contrarian'` to `log_finding` (the agent docs default `owner` via the role; if they don't, tighten the agent doc in Task 8/9 to set it, since this assertion needs it). This is the design §11 known-flaky case — if it fails intermittently with a live session, do NOT loosen it silently; log a `Bug`/`Retro` and revisit the staged flaw, per the brief.

- [ ] **Step 2: Confirm the fast suite still excludes it.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m "not llm" -q`
Expected: suite green; `test_phase1_e2e.py` tests are NOT collected.

- [ ] **Step 3: Run the gate with a live Claude session (on-demand).**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m llm tests/test_phase1_e2e.py -q`
Expected: the three scenarios pass. If `test_contrarian_catches_distinct_flaw` flakes, follow design §11 mitigation (re-stage the flaw to one the contrarian prompt targets) rather than weakening the assertion.

- [ ] **Step 4: Commit.**

```powershell
$msg = "test(e2e): Phase 1 exit-gate (stubborn loop + diagnostic, mixed triage, contrarian) llm-marked"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add mcp-server/tests/test_phase1_e2e.py
git commit -F $f
Remove-Item $f
```

---

## Task 17: Stability check (contradiction-of-prior-approval via git blob compare)

**Goal:** A `stability` module + MCP tool that detects the corrected instability signal (design §8/§12): a Critical flagged on a file whose git blob is byte-identical between two iteration commits AND that the reviewer had previously explicitly approved (Strength/clean) — logging a soft `Pattern` without ever suppressing the Critical. Late discovery and Important->Critical escalation are NOT contradictions.

**Files:**
- Create: `mcp-server/src/agentic_mcp/stability.py`
- Modify: `mcp-server/src/agentic_mcp/server.py` (register `detect_stability_contradiction`)
- Test: `mcp-server/tests/test_stability_check.py`

**Acceptance Criteria:**
- [ ] Identical blob across the two commits + prior explicit approval -> a `Pattern` is logged; returns its id.
- [ ] No prior approval (late discovery) -> returns `None`, logs nothing.
- [ ] Changed blob between commits (legitimate re-review) -> returns `None`, logs nothing.
- [ ] The function never modifies or closes the Critical finding (records only).

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_stability_check.py -q` → suite green.

**Steps:**

- [ ] **Step 1: Write the failing test (builds a real temp git repo).**

Subprocess git calls here use Python list-args (`subprocess.run([...])`), NOT the PowerShell shell, so the PS5.1 heredoc/quote traps do not apply — list args are passed to git directly. Commit identity is set per-invocation with `-c` so the test needs no global git config.

```python
# mcp-server/tests/test_stability_check.py
import subprocess
from pathlib import Path

from agentic_mcp import db, stability


def _git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )


def _init_repo(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    return repo


def test_contradiction_logged_on_identical_blob_with_prior_approval(tmp_path, tmp_db_path):
    repo = _init_repo(tmp_path / "r")
    (repo / "x.py").write_text("def f():\n    return 1\n")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "c1")
    c1 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # Change an UNRELATED file so x.py's blob is identical across c1..c2.
    (repo / "y.py").write_text("y = 1\n")
    _git(repo, "add", "y.py")
    _git(repo, "commit", "-q", "-m", "c2")
    c2 = _git(repo, "rev-parse", "HEAD").stdout.strip()

    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        pid = stability.detect_stability_contradiction(
            conn, str(repo), "x.py", c1, c2, prior_approval=True
        )
        assert pid is not None
        assert db.connect  # sanity
        row = conn.execute("SELECT type, tags FROM pattern WHERE id=?", (pid,)).fetchone()
        assert row[0] == "Pattern"
        assert "stability" in (row[1] or "")
    finally:
        conn.close()


def test_no_contradiction_without_prior_approval(tmp_path, tmp_db_path):
    repo = _init_repo(tmp_path / "r")
    (repo / "x.py").write_text("def f():\n    return 1\n")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "c1")
    c1 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "y.py").write_text("y = 1\n")
    _git(repo, "add", "y.py")
    _git(repo, "commit", "-q", "-m", "c2")
    c2 = _git(repo, "rev-parse", "HEAD").stdout.strip()

    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        pid = stability.detect_stability_contradiction(
            conn, str(repo), "x.py", c1, c2, prior_approval=False
        )
        assert pid is None
        assert conn.execute("SELECT COUNT(*) FROM pattern").fetchone()[0] == 0
    finally:
        conn.close()


def test_no_contradiction_when_blob_changed(tmp_path, tmp_db_path):
    repo = _init_repo(tmp_path / "r")
    (repo / "x.py").write_text("def f():\n    return 1\n")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "c1")
    c1 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "x.py").write_text("def f():\n    return 2\n")  # blob CHANGES
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "c2")
    c2 = _git(repo, "rev-parse", "HEAD").stdout.strip()

    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        pid = stability.detect_stability_contradiction(
            conn, str(repo), "x.py", c1, c2, prior_approval=True
        )
        assert pid is None
    finally:
        conn.close()
```

- [ ] **Step 2: Run to verify failure.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_stability_check.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_mcp.stability'`.

- [ ] **Step 3: Write `stability.py`.**

```python
# mcp-server/src/agentic_mcp/stability.py
"""Stability check: detect contradiction-of-prior-approval (design sections 8, 12).

The instability signal is NOT 'a Critical on an unchanged file' (that punishes
legitimate late discovery). It is a Critical on a file whose git blob is
byte-identical between two iteration commits AND that the reviewer had
previously EXPLICITLY approved. We record a soft Pattern; we never suppress the
Critical (Phase 1 detects, Phase 4 calibration judges).
"""
from __future__ import annotations

import sqlite3
import subprocess

from . import nodes


def _blob_sha(repo: str, commit: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"],
        cwd=repo, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def detect_stability_contradiction(
    conn: sqlite3.Connection,
    repo: str,
    path: str,
    commit_before: str,
    commit_after: str,
    prior_approval: bool,
) -> str | None:
    """Return a Pattern id if a contradiction is detected, else None.

    prior_approval: did the reviewer explicitly approve this file in an earlier
    round (logged a Strength on it, or marked it clean)? Late discovery passes
    False here and is never a contradiction.
    """
    if not prior_approval:
        return None  # late discovery is legitimate, not instability
    before = _blob_sha(repo, commit_before, path)
    after = _blob_sha(repo, commit_after, path)
    if before is None or after is None or before != after:
        return None  # code changed (or path missing) -> legitimate re-review
    return nodes.create_node(
        conn, "Pattern", status="open", owner="system", severity="Suggested",
        body=(
            f"stability: {path} was flagged Critical on byte-identical blob "
            f"{after} ({commit_before[:8]}..{commit_after[:8]}) after a prior "
            "explicit approval. Calibration signal only; the Critical is still "
            "actioned. Phase 1 records, Phase 4 calibration judges."
        ),
        tags="stability,contradiction",
    )
```

- [ ] **Step 4: Register the MCP tool in `server.py`.**

Add the import near the others: `from . import stability as stability_mod`. Add the `Tool(...)` to `list_tools`:

```python
        Tool(
            name="detect_stability_contradiction",
            description="Log a soft Pattern if a Critical hits a byte-identical file the reviewer previously approved. Records only; never suppresses the Critical.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "path": {"type": "string"},
                    "commit_before": {"type": "string"},
                    "commit_after": {"type": "string"},
                    "prior_approval": {"type": "boolean"},
                },
                "required": ["repo", "path", "commit_before", "commit_after", "prior_approval"],
            },
        ),
```

Add the `call_tool` branch:

```python
        if name == "detect_stability_contradiction":
            pid = stability_mod.detect_stability_contradiction(
                conn, arguments["repo"], arguments["path"],
                arguments["commit_before"], arguments["commit_after"],
                arguments["prior_approval"],
            )
            return _ok({"pattern_id": pid})
```

- [ ] **Step 5: Run to verify pass, then full suite.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest tests/test_stability_check.py -q` → suite green.
Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m "not llm" -q` → suite green.

- [ ] **Step 6: Commit.**

```powershell
$msg = "feat(stability): contradiction-of-prior-approval detector + MCP tool (design sections 8,12)"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add mcp-server/src/agentic_mcp/stability.py mcp-server/src/agentic_mcp/server.py mcp-server/tests/test_stability_check.py
git commit -F $f
Remove-Item $f
```

---

## Task 18: Docs update + plan-coverage self-review + final commit

**Goal:** Update the README with the Phase 1 surface (entities, tools, agents, commands), confirm the full fast suite is green and the MCP version is pinned, run the plan-vs-spec coverage self-review, and land the final Phase 1 commit.

**Files:**
- Modify: `README.md` (Phase 1 section + status table)
- Modify: `docs/plans/2026-05-20-phase-1-build-pipeline.md.tasks.json` (flip all task statuses to `completed`)

**Acceptance Criteria:**
- [ ] README documents: the `CriticalLoop` entity; the seven new tools + `detect_stability_contradiction`; the `code-reviewer`/`contrarian`/`spec-writer` agents + builder loop-fix mode; the `dispatch`/`review-pr`/`new-spec` commands; and how to run the `llm` gate.
- [ ] `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m "not llm" -q` is green.
- [ ] `mcp==1.27.1` remains pinned in `pyproject.toml` (PLAN-TEMPLATE-CHECKLIST §6).
- [ ] Coverage self-review maps each design §13 criterion (1-8) to the task that satisfies it (table below); no gaps.

**Verify:** `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m "not llm" -q` → suite green; manual confirmation the README sections exist.

**Steps:**

- [ ] **Step 1: Coverage self-review (design §13 criteria -> tasks).**

Confirm each maps to a green test (fast suite) or the llm gate:

| Spec §13 criterion | Satisfied by | Verify |
|---|---|---|
| 1. CriticalLoop + migrations apply to existing graph.db | Tasks 0, 1 | `test_migrations.py`, `test_critical_loop.py` |
| 2. Loop tools round-trip across a fresh connection | Task 2 | `test_critical_loop.py` |
| 3. failed_layer enum rejects/accepts | Task 5 | `test_retro_layer.py` |
| 4. dispatched_at immutability + supersede | Task 3 | `test_dispatch_immutability.py` |
| 5. spec-writer validates inline, refuses rejected spec | Task 10 | `test_agent_docs.py::test_spec_writer_doc` (+ llm e2e behavioral) |
| 6. exit-gate: diagnostic at 3, resolve at 4 | Tasks 14-16 | `test_phase1_e2e.py -m llm` |
| 7. mixed-severity auto-triage | Tasks 4, 16 | `test_triage.py`, `test_phase1_e2e.py::test_mixed_severity -m llm` |
| 8. stability logs Pattern on contradiction, silent on late discovery | Task 17 | `test_stability_check.py` |

If any row has no green test, STOP and add the missing task before declaring the plan done. (Criterion 5's mechanical guard is the doc-structure test; its behavioral proof is the llm e2e — note this honestly in the README rather than overclaiming.)

- [ ] **Step 2: Update `README.md` with the Phase 1 surface.**

Add a "## Phase 1: Build pipeline + review loop" section documenting the entity, tools, agents, commands, and the `llm` gate, and update any Phase-0 status table to mark Phase 1 shipped. (Match the existing README's heading style; keep ASCII.)

- [ ] **Step 3: Confirm the fast suite is green and the SDK is pinned.**

Run: `cd mcp-server && .\.venv\Scripts\python.exe -m pytest -m "not llm" -q` → suite green.
Confirm `pyproject.toml` still has `mcp==1.27.1`.

- [ ] **Step 4: Flip every task in the `.tasks.json` sidecar to `completed`** (cross-session resume depends on it — PLAN-TEMPLATE-CHECKLIST §5).

- [ ] **Step 5: Final commit.**

```powershell
$msg = "docs(readme): Phase 1 surface + coverage self-review; mark plan complete"
$f = New-TemporaryFile
Set-Content -Path $f -Value $msg -Encoding ascii   # ascii, NOT utf8: utf8 writes a BOM that lands in the commit subject
git add README.md docs/plans/2026-05-20-phase-1-build-pipeline.md.tasks.json
git commit -F $f
Remove-Item $f
```

---

## Self-Review (writing-plans skill)

**Spec coverage:** all eight design §13 criteria map to a task (table in Task 18 §1). The four falsifier scenarios (design §1) map to Task 16's three e2e tests (scenario 1 the planted-bug resolution and scenario 2 the stubborn diagnostic are both exercised by `test_stubborn_critical_diagnostic_then_resolve`; 3 by `test_mixed_severity`; 4 by `test_contrarian_catches_distinct_flaw`).

**Placeholder scan:** every code/markdown step ships full content; no TBD/TODO/"similar to Task N". The one deliberately deferred unknown — the exact `claude -p` JSON key — is handled as Task 14's Step-1 spike with a written fallback, not a placeholder.

**Type consistency:** `log_finding` gains `criterion_index`/`loop_iteration` (Task 4) and is called with them in Task 16; `record_triage(conn, finding_id, decision)`, `log_retro(conn, body, failed_layer, caused_by_finding_id=...)`, `start/advance/resolve_critical_loop`, `dispatch_spec(conn, spec_id)`, and `detect_stability_contradiction(conn, repo, path, commit_before, commit_after, prior_approval)` signatures match between their defining task, their server.py registration (Tasks 6, 17), and their test call sites. `dispatched_at` is registered in `nodes.EXTRA_OPTIONAL["Spec"]` (Task 3 fix) and the three Finding columns in `EXTRA_OPTIONAL["Finding"]` (Task 4), so `update_node`/`create_node` actually persist them.

> **Plan complete (Tasks 0-18).** Phase 1 EXECUTION should run in a fresh session and dogfood Phase 0 (builder + spec-checker + validate_spec build Phase 1's pieces, per Gating-4). The sidecar `.tasks.json` and native tasks track resume state.

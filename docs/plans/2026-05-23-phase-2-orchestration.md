# Phase 2: Orchestration & Parallelism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the orchestrator that runs multiple builder/reviewer teams in parallel from the graph board - stateless single-tick scheduling, headless ephemeral worker/reviewer processes in isolated worktrees, serial-when-shared via claim overlap, scheduled weeding, and trust-weighting calibration.

**Architecture:** The graph (`graph.db`) is the board. `/agentic:orchestrate --once` runs one stateless tick per process (hydrates from the graph, dispatches a pool of headless `claude -p` workers/reviewers into per-team worktrees, harvests structured results, merges in DAG order, weeds, calibrates, exits). `/loop` or cron owns the cadence. Three new auxiliary tables (`claim`, `calibration`, plus `spec.stale_flagged_at`) and seven new MCP tools back the scheduler.

**Tech Stack:** Python 3.12, SQLite (stdlib `sqlite3`), `mcp` SDK (stdio server), pytest, headless `claude` CLI (Max OAuth, `--permission-mode bypassPermissions`), git worktrees, PowerShell 5.1 host.

**Design source:** `docs/superpowers/specs/2026-05-23-phase-2-orchestration-design.md`. Builds on PR #2's versioned-migration framework (current `SCHEMA_VERSION = 2`).

**Conventions (read once):**
- New domain logic lives in a focused module `src/agentic_mcp/<name>.py`; every function takes the open `sqlite3.Connection` as its first arg and calls `conn.commit()` after writes (mirrors `loops.py`, `findings.py`).
- `claim` and `calibration` are **auxiliary tables, not graph node types** - they do NOT go in `nodes.ENTITY_TABLES`; they have their own modules and are queried directly.
- Tests use the `tmp_db_path` fixture (`tests/conftest.py`) and the `_mk_conn` helper pattern: `db.init_db(p); return db.connect(p)`.
- Timestamps: `datetime.now(timezone.utc).isoformat(timespec="seconds")` (copy the `_now()` helper).
- Run the fast suite from `mcp-server/`: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`.
- ASCII only in any `.ps1`/command-doc string literals (PS 5.1 cp1252).

---

### Task 0: Schema v3 migration - `claim` + `calibration` tables + `spec.stale_flagged_at`

**Goal:** Extend the schema and the versioned-migration framework to v3 with the two new auxiliary tables and the stale-spec column, idempotently.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/schema.sql` (append two CREATE TABLE blocks; add column to `spec`)
- Modify: `mcp-server/src/agentic_mcp/migrations.py`
- Test: `mcp-server/tests/test_migrations.py`

**Acceptance Criteria:**
- [ ] Fresh `init_db` produces a DB at `user_version = 3` with `claim` and `calibration` tables and a `spec.stale_flagged_at` column.
- [ ] A simulated v2 DB upgraded via `apply_migrations` reaches v3 and gains the new tables/column without data loss.
- [ ] Running `apply_migrations` twice is a no-op (no error, same result).

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_migrations.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Add to `mcp-server/tests/test_migrations.py`:

```python
def test_fresh_db_is_v3_with_phase2_tables(tmp_db_path):
    from agentic_mcp import db
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"claim", "calibration"} <= names
        spec_cols = {r[1] for r in conn.execute("PRAGMA table_info(spec)")}
        assert "stale_flagged_at" in spec_cols
    finally:
        conn.close()


def test_v2_db_upgrades_to_v3(tmp_db_path):
    import sqlite3
    from agentic_mcp import db, migrations
    # Build a fresh DB then force it back to v2 to simulate a pre-Phase-2 file.
    db.init_db(tmp_db_path)
    raw = sqlite3.connect(str(tmp_db_path))
    raw.executescript("DROP TABLE IF EXISTS claim; DROP TABLE IF EXISTS calibration;")
    raw.execute("PRAGMA user_version = 2")
    raw.commit()
    raw.close()

    conn = db.connect(tmp_db_path)  # connect() runs apply_migrations
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"claim", "calibration"} <= names
        # idempotent re-run
        migrations.apply_migrations(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_migrations.py::test_fresh_db_is_v3_with_phase2_tables -v`
Expected: FAIL (user_version is 2; `claim`/`calibration` missing)

- [ ] **Step 3: Add the new tables to `schema.sql`**

Append to `mcp-server/src/agentic_mcp/schema.sql` (after the `arch_debt` table):

```sql
CREATE TABLE IF NOT EXISTS claim (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  scope_paths TEXT NOT NULL,            -- JSON array of repo-relative path globs
  worktree TEXT,
  branch TEXT,
  status TEXT NOT NULL CHECK(status IN ('held','released')),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calibration (
  role TEXT PRIMARY KEY,
  observations INTEGER NOT NULL DEFAULT 0,
  hits INTEGER NOT NULL DEFAULT 0,
  misses INTEGER NOT NULL DEFAULT 0,
  score REAL NOT NULL DEFAULT 0.5,
  last_adjusted_at TEXT,
  distrusted INTEGER NOT NULL DEFAULT 0  -- 0|1 boolean
);
```

Add the `stale_flagged_at` column to the existing `spec` CREATE TABLE block (add as the last column before the closing paren):

```sql
  stale_flagged_at TEXT
```

- [ ] **Step 4: Extend `migrations.py` to v3**

In `mcp-server/src/agentic_mcp/migrations.py`, change the version constants:

```python
PHASE_1_VERSION = 1
PHASE_2_VERSION = 2
PHASE_3_VERSION = 3   # schema version, not project phase: integration-layer change took v2
SCHEMA_VERSION = PHASE_3_VERSION
```

Add the v3 DDL constant near the other DDL strings:

```python
_PHASE_3_DDL = """
CREATE TABLE IF NOT EXISTS claim (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  scope_paths TEXT NOT NULL,
  worktree TEXT,
  branch TEXT,
  status TEXT NOT NULL CHECK(status IN ('held','released')),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calibration (
  role TEXT PRIMARY KEY,
  observations INTEGER NOT NULL DEFAULT 0,
  hits INTEGER NOT NULL DEFAULT 0,
  misses INTEGER NOT NULL DEFAULT 0,
  score REAL NOT NULL DEFAULT 0.5,
  last_adjusted_at TEXT,
  distrusted INTEGER NOT NULL DEFAULT 0
);
"""
```

Add the migration function (after `_migrate_to_phase_2`):

```python
def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    # claim + calibration are additive tables; stale_flagged_at is an additive
    # column. All guarded/idempotent, so no table rebuild is needed here.
    conn.executescript(_PHASE_3_DDL)
    _add_column_if_missing(conn, "spec", "stale_flagged_at", "TEXT")
```

Wire it into `apply_migrations` (after the `version < PHASE_2_VERSION` block, before the `PRAGMA user_version` write):

```python
    if version < PHASE_3_VERSION:
        _migrate_to_v3(conn)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_migrations.py -v`
Expected: PASS (all migration tests)

- [ ] **Step 6: Run the full fast suite (guard against regressions)**

Run: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: all pass (previously 110, now +2)

- [ ] **Step 7: Commit**

```bash
git add mcp-server/src/agentic_mcp/schema.sql mcp-server/src/agentic_mcp/migrations.py mcp-server/tests/test_migrations.py
git commit -m "feat(schema): v3 migration - claim + calibration tables + spec.stale_flagged_at"
```

---

### Task 1: `claims.py` - claim_scope, release_claim, detect_overlap

**Goal:** Record per-task scope claims, detect overlap against open claims, and compute the maximum non-overlapping batch from a ready set (the serial-when-shared core).

**Files:**
- Create: `mcp-server/src/agentic_mcp/claims.py`
- Test: `mcp-server/tests/test_claims.py`

**Acceptance Criteria:**
- [ ] `claim_scope` inserts a held claim and returns its id; `release_claim` flips status to `released`.
- [ ] `claim_scope` returns a conflict (raises `ClaimConflict`) when the requested paths overlap any *held* claim.
- [ ] `detect_overlap(candidates)` returns the largest subset of candidate task specs whose path sets are mutually disjoint (greedy, deterministic by input order).
- [ ] Overlap is glob-aware: `src/a/*` overlaps `src/a/b.py`.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_claims.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_claims.py`:

```python
"""Claim lifecycle + serial-when-shared overlap detection."""
import pytest

from agentic_mcp import db, claims


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def test_claim_then_release(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        cid = claims.claim_scope(conn, "task-1", ["src/a/*"], worktree="wt1", branch="b1")
        rows = list(conn.execute("SELECT status FROM claim WHERE id=?", (cid,)))
        assert rows[0][0] == "held"
        claims.release_claim(conn, cid)
        rows = list(conn.execute("SELECT status FROM claim WHERE id=?", (cid,)))
        assert rows[0][0] == "released"
    finally:
        conn.close()


def test_overlapping_claim_conflicts(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        claims.claim_scope(conn, "task-1", ["src/a/*"])
        with pytest.raises(claims.ClaimConflict):
            claims.claim_scope(conn, "task-2", ["src/a/b.py"])
    finally:
        conn.close()


def test_released_claim_does_not_conflict(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        cid = claims.claim_scope(conn, "task-1", ["src/a/*"])
        claims.release_claim(conn, cid)
        # no raise:
        claims.claim_scope(conn, "task-2", ["src/a/b.py"])
    finally:
        conn.close()


def test_detect_overlap_returns_max_disjoint_batch(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        candidates = [
            {"task_id": "t1", "scope_paths": ["src/a/*"]},
            {"task_id": "t2", "scope_paths": ["src/a/x.py"]},  # overlaps t1 -> dropped
            {"task_id": "t3", "scope_paths": ["src/b/*"]},
            {"task_id": "t4", "scope_paths": ["src/c/*"]},
        ]
        batch = claims.detect_overlap(candidates)
        assert [c["task_id"] for c in batch] == ["t1", "t3", "t4"]
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_claims.py -v`
Expected: FAIL (`No module named 'agentic_mcp.claims'`)

- [ ] **Step 3: Implement `claims.py`**

Create `mcp-server/src/agentic_mcp/claims.py`:

```python
"""Scope claims for serial-when-shared scheduling.

A claim records the repo-relative path globs a task will touch while a worker
holds a worktree. claim_scope refuses to record a held claim that overlaps an
existing held claim (so two parallel teams never touch the same surface).
detect_overlap is the pure batching helper the scheduler uses to pick the next
parallel set from a list of candidate task specs.

Claims are an auxiliary table, not a graph node type.
"""
from __future__ import annotations

import fnmatch
import json
import sqlite3
import uuid
from datetime import datetime, timezone


class ClaimConflict(RuntimeError):
    """Raised when a requested claim overlaps an already-held claim."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _paths_overlap(a: list[str], b: list[str]) -> bool:
    """True if any path/glob in *a* matches any in *b* (either direction)."""
    for pa in a:
        for pb in b:
            if pa == pb or fnmatch.fnmatch(pa, pb) or fnmatch.fnmatch(pb, pa):
                return True
    return False


def _held_claims(conn: sqlite3.Connection) -> list[list[str]]:
    return [
        json.loads(r[0])
        for r in conn.execute("SELECT scope_paths FROM claim WHERE status='held'")
    ]


def claim_scope(
    conn: sqlite3.Connection,
    task_id: str,
    scope_paths: list[str],
    worktree: str | None = None,
    branch: str | None = None,
) -> str:
    for held in _held_claims(conn):
        if _paths_overlap(scope_paths, held):
            raise ClaimConflict(
                f"task {task_id} scope {scope_paths} overlaps held claim {held}"
            )
    cid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO claim(id, task_id, scope_paths, worktree, branch, status, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (cid, task_id, json.dumps(scope_paths), worktree, branch, "held", _now()),
    )
    conn.commit()
    return cid


def release_claim(conn: sqlite3.Connection, claim_id: str) -> None:
    conn.execute("UPDATE claim SET status='released' WHERE id=?", (claim_id,))
    conn.commit()


def detect_overlap(candidates: list[dict]) -> list[dict]:
    """Greedy max-disjoint batch.

    *candidates* is a list of dicts each with a 'scope_paths' list. Returns the
    subset (in input order) whose path sets are mutually disjoint - the first
    candidate always wins, later ones join only if they overlap nothing already
    accepted.
    """
    accepted: list[dict] = []
    taken: list[str] = []
    for c in candidates:
        paths = c["scope_paths"]
        if not _paths_overlap(paths, taken):
            accepted.append(c)
            taken = taken + list(paths)
    return accepted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_claims.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/claims.py mcp-server/tests/test_claims.py
git commit -m "feat(claims): scope claims + serial-when-shared overlap detection"
```

---

### Task 2: `weeding.py` - flag_stale + stale-spec detection

**Goal:** Surface graph nodes untouched beyond a threshold and dispatched Specs with no commit progress, by stamping `stale_flagged_at` / returning a triage list. Surface only - never auto-close.

**Files:**
- Create: `mcp-server/src/agentic_mcp/weeding.py`
- Test: `mcp-server/tests/test_weeding.py`

**Acceptance Criteria:**
- [ ] `find_stale_nodes(conn, days)` returns nodes whose `last_touched` is older than `days`, excluding `resolved`/`done`/`merged` statuses.
- [ ] `flag_stale_specs(conn, days)` stamps `stale_flagged_at` on dispatched Specs whose `last_touched` is older than `days` and clears it on ones that are fresh again; returns the list of currently-stale spec ids.
- [ ] A freshly-touched node/spec is never flagged.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_weeding.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_weeding.py`:

```python
"""Anti-rot weeding + stale-spec detection."""
import json
from datetime import datetime, timedelta, timezone

from agentic_mcp import db, nodes, weeding


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def _old_iso(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _dispatched_spec(conn, last_touched):
    sid = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
        feedback_loop="if a user reports a bug we open a PR and write a retro",
    )
    conn.execute("UPDATE spec SET last_touched=? WHERE id=?", (last_touched, sid))
    conn.commit()
    return sid


def test_find_stale_nodes_flags_old_excludes_fresh(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        old = _dispatched_spec(conn, _old_iso(30))
        fresh = _dispatched_spec(conn, _old_iso(1))
        stale_ids = {n["id"] for n in weeding.find_stale_nodes(conn, days=14)}
        assert old in stale_ids
        assert fresh not in stale_ids
    finally:
        conn.close()


def test_flag_stale_specs_stamps_and_clears(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        sid = _dispatched_spec(conn, _old_iso(30))
        flagged = weeding.flag_stale_specs(conn, days=14)
        assert sid in flagged
        assert nodes.get_node(conn, sid)["stale_flagged_at"] is not None
        # touch it fresh, re-run -> cleared
        conn.execute("UPDATE spec SET last_touched=? WHERE id=?", (_old_iso(0), sid))
        conn.commit()
        flagged2 = weeding.flag_stale_specs(conn, days=14)
        assert sid not in flagged2
        assert nodes.get_node(conn, sid)["stale_flagged_at"] is None
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_weeding.py -v`
Expected: FAIL (`No module named 'agentic_mcp.weeding'`)

- [ ] **Step 3: Implement `weeding.py`**

Create `mcp-server/src/agentic_mcp/weeding.py`:

```python
"""Scheduled anti-rot weeding + stale-spec detection.

Surfaces stale work for triage; never auto-closes. find_stale_nodes scans every
entity table for rows older than the threshold (excluding terminal statuses).
flag_stale_specs stamps/clears spec.stale_flagged_at so the orchestrator can
escalate dispatched-but-stalled specs.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import nodes

TERMINAL_STATUSES = {"resolved", "done", "merged", "closed", "released"}


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def find_stale_nodes(conn: sqlite3.Connection, days: int = 14) -> list[dict]:
    cutoff = _cutoff_iso(days)
    stale: list[dict] = []
    for table in nodes.ENTITY_TABLES.values():
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "last_touched" not in cols or "status" not in cols:
            continue
        for (nid,) in conn.execute(
            f"SELECT id FROM {table} WHERE last_touched < ? AND status NOT IN "
            f"({','.join('?' * len(TERMINAL_STATUSES))})",
            (cutoff, *sorted(TERMINAL_STATUSES)),
        ):
            stale.append(nodes.get_node(conn, nid))
    return stale


def flag_stale_specs(conn: sqlite3.Connection, days: int = 14) -> list[str]:
    cutoff = _cutoff_iso(days)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    flagged: list[str] = []
    for (sid, last_touched, flag) in conn.execute(
        "SELECT id, last_touched, stale_flagged_at FROM spec WHERE status='dispatched'"
    ).fetchall():
        is_stale = last_touched < cutoff
        if is_stale:
            flagged.append(sid)
            if flag is None:
                conn.execute("UPDATE spec SET stale_flagged_at=? WHERE id=?", (now, sid))
        elif flag is not None:
            conn.execute("UPDATE spec SET stale_flagged_at=NULL WHERE id=?", (sid,))
    conn.commit()
    return flagged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_weeding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/weeding.py mcp-server/tests/test_weeding.py
git commit -m "feat(weeding): stale-node scan + dispatched-spec stale flagging"
```

---

### Task 3: `calibration.py` - record_outcome, get_calibration, adjust_trust

**Goal:** Track each role's hit/miss record, compute a smoothed score, and flip the `distrusted` flag when the score crosses the floor/ceiling thresholds.

**Files:**
- Create: `mcp-server/src/agentic_mcp/calibration.py`
- Test: `mcp-server/tests/test_calibration.py`

**Acceptance Criteria:**
- [ ] `record_outcome(conn, role, hit=True/False)` upserts the role row and updates `observations`, `hits`/`misses`, and the Laplace-smoothed `score`.
- [ ] `get_calibration(conn, role)` returns the current row (score + distrusted) for a known role and a default (score 0.5, distrusted 0, observations 0) for an unknown one.
- [ ] `adjust_trust(conn, role)` sets `distrusted=1` + stamps `last_adjusted_at` when score < floor (0.4); clears it when score > ceiling (0.7); returns `{"adjusted": bool, "distrusted": int}`. `adjusted` is True only when the flag actually changed.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_calibration.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_calibration.py`:

```python
"""Per-role trust-weighting calibration."""
from agentic_mcp import db, calibration


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def test_unknown_role_has_neutral_default(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        c = calibration.get_calibration(conn, "code-reviewer")
        assert c["score"] == 0.5
        assert c["distrusted"] == 0
        assert c["observations"] == 0
    finally:
        conn.close()


def test_record_outcome_updates_score(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(5):
            calibration.record_outcome(conn, "code-reviewer", hit=True)
        c = calibration.get_calibration(conn, "code-reviewer")
        assert c["observations"] == 5
        assert c["hits"] == 5
        assert c["score"] > 0.7  # 6/7 with Laplace smoothing
    finally:
        conn.close()


def test_adjust_trust_fires_on_low_score(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(8):
            calibration.record_outcome(conn, "contrarian", hit=False)
        res = calibration.adjust_trust(conn, "contrarian")
        assert res["adjusted"] is True
        assert res["distrusted"] == 1
        assert calibration.get_calibration(conn, "contrarian")["last_adjusted_at"] is not None
        # second call: already distrusted, score still low -> no change
        res2 = calibration.adjust_trust(conn, "contrarian")
        assert res2["adjusted"] is False
    finally:
        conn.close()


def test_adjust_trust_clears_on_recovery(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(8):
            calibration.record_outcome(conn, "contrarian", hit=False)
        calibration.adjust_trust(conn, "contrarian")  # distrust set
        for _ in range(40):
            calibration.record_outcome(conn, "contrarian", hit=True)
        res = calibration.adjust_trust(conn, "contrarian")  # score now high
        assert res["adjusted"] is True
        assert res["distrusted"] == 0
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_calibration.py -v`
Expected: FAIL (`No module named 'agentic_mcp.calibration'`)

- [ ] **Step 3: Implement `calibration.py`**

Create `mcp-server/src/agentic_mcp/calibration.py`:

```python
"""Per-role confidence calibration (trust-weighting).

Each role accrues hit/miss observations; score is a Laplace-smoothed hit-rate.
When the score crosses the floor the role is marked distrusted (the orchestrator
then requires a second reviewer and discounts that role's Criticals); sustained
recovery above the ceiling clears it. adjust_trust reports whether the flag
actually changed - a flip is the "calibration adjustment fired" the exit gate
checks for.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

FLOOR = 0.4
CEILING = 0.7
_SMOOTHING = 1  # Laplace add-one


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _score(hits: int, observations: int) -> float:
    return (hits + _SMOOTHING) / (observations + 2 * _SMOOTHING)


def _ensure_row(conn: sqlite3.Connection, role: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO calibration(role, score) VALUES (?, 0.5)", (role,)
    )


def record_outcome(conn: sqlite3.Connection, role: str, hit: bool) -> None:
    _ensure_row(conn, role)
    col = "hits" if hit else "misses"
    conn.execute(
        f"UPDATE calibration SET observations = observations + 1, {col} = {col} + 1 "
        "WHERE role=?",
        (role,),
    )
    row = conn.execute(
        "SELECT hits, observations FROM calibration WHERE role=?", (role,)
    ).fetchone()
    conn.execute(
        "UPDATE calibration SET score=? WHERE role=?",
        (_score(row[0], row[1]), role),
    )
    conn.commit()


def get_calibration(conn: sqlite3.Connection, role: str) -> dict:
    row = conn.execute(
        "SELECT role, observations, hits, misses, score, last_adjusted_at, distrusted "
        "FROM calibration WHERE role=?",
        (role,),
    ).fetchone()
    if row is None:
        return {"role": role, "observations": 0, "hits": 0, "misses": 0,
                "score": 0.5, "last_adjusted_at": None, "distrusted": 0}
    keys = ["role", "observations", "hits", "misses", "score", "last_adjusted_at", "distrusted"]
    return dict(zip(keys, row))


def adjust_trust(conn: sqlite3.Connection, role: str) -> dict:
    c = get_calibration(conn, role)
    current = c["distrusted"]
    target = current
    if c["score"] < FLOOR:
        target = 1
    elif c["score"] > CEILING:
        target = 0
    adjusted = target != current
    if adjusted:
        _ensure_row(conn, role)
        conn.execute(
            "UPDATE calibration SET distrusted=?, last_adjusted_at=? WHERE role=?",
            (target, _now(), role),
        )
        conn.commit()
    return {"adjusted": adjusted, "distrusted": target}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_calibration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/calibration.py mcp-server/tests/test_calibration.py
git commit -m "feat(calibration): trust-weighting score + distrust threshold flip"
```

---

### Task 4: Register the 7 new MCP tools in `server.py`

**Goal:** Expose `claim_scope`, `release_claim`, `detect_overlap`, `flag_stale`, `record_outcome`, `get_calibration`, `adjust_trust` over the stdio MCP server.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/server.py`
- Test: `mcp-server/tests/test_server.py`

**Acceptance Criteria:**
- [ ] `list_tools()` includes all 7 new tool names (total 25).
- [ ] `call_tool` dispatches each to its module function and returns the `_ok` JSON shape; a `ClaimConflict` is reported via the `_err` path (not an unhandled crash).

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_server.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Add to `mcp-server/tests/test_server.py`:

```python
import asyncio
import json

from agentic_mcp import server


def _call(name, args):
    return asyncio.run(server.call_tool(name, args))


def test_phase2_tools_listed():
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"claim_scope", "release_claim", "detect_overlap", "flag_stale",
            "record_outcome", "get_calibration", "adjust_trust"} <= names
    assert len(names) == 25


def test_claim_scope_and_overlap_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    out = _call("claim_scope", {"task_id": "t1", "scope_paths": ["src/a/*"]})
    payload = json.loads(out[0].text)
    assert "id" in payload
    # overlapping claim -> error path, not a crash
    out2 = _call("claim_scope", {"task_id": "t2", "scope_paths": ["src/a/b.py"]})
    assert "error" in json.loads(out2[0].text)


def test_calibration_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    _call("record_outcome", {"role": "code-reviewer", "hit": False})
    out = _call("get_calibration", {"role": "code-reviewer"})
    assert json.loads(out[0].text)["observations"] == 1
```

> Note: if existing `test_server.py` already asserts a specific tool count, update that assertion to 25 in this step.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_server.py::test_phase2_tools_listed -v`
Expected: FAIL (new tools not listed; count != 25)

- [ ] **Step 3: Add imports + tool registrations**

In `mcp-server/src/agentic_mcp/server.py`, add to the import block:

```python
from . import claims as claims_mod
from . import weeding as weeding_mod
from . import calibration as calib_mod
```

Append these `Tool(...)` entries to the list returned by `list_tools()` (before the closing `]`):

```python
        Tool(
            name="claim_scope",
            description="Record a held scope claim for a task; errors if it overlaps an open claim.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "scope_paths": {"type": "array", "items": {"type": "string"}},
                    "worktree": {"type": "string"},
                    "branch": {"type": "string"},
                },
                "required": ["task_id", "scope_paths"],
            },
        ),
        Tool(
            name="release_claim",
            description="Release a held scope claim by id.",
            inputSchema={
                "type": "object",
                "properties": {"claim_id": {"type": "string"}},
                "required": ["claim_id"],
            },
        ),
        Tool(
            name="detect_overlap",
            description="Return the maximum non-overlapping batch from candidate task scope specs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidates": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["candidates"],
            },
        ),
        Tool(
            name="flag_stale",
            description="Flag dispatched Specs untouched beyond N days; returns stale spec ids.",
            inputSchema={
                "type": "object",
                "properties": {"days": {"type": "integer", "default": 14}},
            },
        ),
        Tool(
            name="record_outcome",
            description="Append a hit/miss observation to a role's calibration record.",
            inputSchema={
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "hit": {"type": "boolean"},
                },
                "required": ["role", "hit"],
            },
        ),
        Tool(
            name="get_calibration",
            description="Read a role's calibration row (score + distrusted flag).",
            inputSchema={
                "type": "object",
                "properties": {"role": {"type": "string"}},
                "required": ["role"],
            },
        ),
        Tool(
            name="adjust_trust",
            description="Flip a role's distrust flag if its score crossed the floor/ceiling; reports whether it changed.",
            inputSchema={
                "type": "object",
                "properties": {"role": {"type": "string"}},
                "required": ["role"],
            },
        ),
```

- [ ] **Step 4: Add dispatch branches in `call_tool`**

In `call_tool`, before the final `return _err(f"unknown tool: {name}")`:

```python
        if name == "claim_scope":
            cid = claims_mod.claim_scope(
                conn, arguments["task_id"], arguments["scope_paths"],
                worktree=arguments.get("worktree"), branch=arguments.get("branch"),
            )
            return _ok({"id": cid})
        if name == "release_claim":
            claims_mod.release_claim(conn, arguments["claim_id"])
            return _ok({"ok": True})
        if name == "detect_overlap":
            return _ok({"batch": claims_mod.detect_overlap(arguments["candidates"])})
        if name == "flag_stale":
            return _ok({"stale": weeding_mod.flag_stale_specs(conn, arguments.get("days", 14))})
        if name == "record_outcome":
            calib_mod.record_outcome(conn, arguments["role"], arguments["hit"])
            return _ok({"ok": True})
        if name == "get_calibration":
            return _ok(calib_mod.get_calibration(conn, arguments["role"]))
        if name == "adjust_trust":
            return _ok(calib_mod.adjust_trust(conn, arguments["role"]))
```

> The existing `except Exception` wrapper already routes `ClaimConflict` to `_err`, satisfying the no-crash criterion.

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_server.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mcp-server/src/agentic_mcp/server.py mcp-server/tests/test_server.py
git commit -m "feat(server): register 7 Phase 2 orchestration tools (25 total)"
```

---

### Task 5: Promote `llm_harness.py` to the package + add `Pool`

**Goal:** Move the headless-`claude` subprocess engine from `tests/` into the package as `headless.py` (so it is importable at runtime, not just under test) and add a `Pool` wrapper that launches/harvests up to N processes with backfill and per-process timeout.

**Files:**
- Create: `mcp-server/src/agentic_mcp/headless.py` (moved content + `Pool`)
- Modify: `mcp-server/tests/llm_harness.py` (becomes a thin re-export shim so existing e2e imports keep working)
- Test: `mcp-server/tests/test_headless.py`

**Acceptance Criteria:**
- [ ] All functions previously in `tests/llm_harness.py` (`run_claude_headless`, `result_text`, `stage_mcp_config`, `claude_on_path`, `ClaudeUnavailable`, `_kill_tree`) are importable from `agentic_mcp.headless`.
- [ ] `tests/llm_harness.py` re-exports them so `test_phase1_e2e.py` and `test_llm_harness.py` still pass unchanged.
- [ ] `Pool(max_workers=N).run(jobs, launch_fn)` launches at most N concurrent jobs, backfills as each finishes, and returns one result dict per job. Tested with a stub `launch_fn` (no real `claude`).

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_headless.py tests/test_llm_harness.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing test for the new home + Pool**

Create `mcp-server/tests/test_headless.py`:

```python
"""Pool wrapper + harness importable from the package."""
import time

from agentic_mcp import headless


def test_harness_importable_from_package():
    assert hasattr(headless, "run_claude_headless")
    assert hasattr(headless, "result_text")
    assert hasattr(headless, "stage_mcp_config")
    assert issubclass(headless.ClaudeUnavailable, RuntimeError)


def test_pool_runs_all_jobs_with_cap():
    jobs = [{"task_id": f"t{i}"} for i in range(5)]
    concurrent = {"now": 0, "max": 0}

    def launch(job):
        concurrent["now"] += 1
        concurrent["max"] = max(concurrent["max"], concurrent["now"])
        time.sleep(0.05)
        concurrent["now"] -= 1
        return {"task_id": job["task_id"], "ok": True}

    pool = headless.Pool(max_workers=2)
    results = pool.run(jobs, launch)
    assert {r["task_id"] for r in results} == {f"t{i}" for i in range(5)}
    assert all(r["ok"] for r in results)
    assert concurrent["max"] <= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_headless.py -v`
Expected: FAIL (`No module named 'agentic_mcp.headless'`)

- [ ] **Step 3: Create `headless.py` (moved content + Pool)**

Create `mcp-server/src/agentic_mcp/headless.py` with the FULL current contents of `tests/llm_harness.py` (copy `ClaudeUnavailable`, `_kill_tree`, `claude_on_path`, `_claude_exe`, `stage_mcp_config`, `run_claude_headless`, `result_text` verbatim), then append the `Pool` class:

```python
import concurrent.futures


class Pool:
    """Run jobs through a thread pool capped at *max_workers*.

    Each job is handed to *launch_fn* (which performs the blocking
    run_claude_headless call in production, or a stub in tests). Threads are the
    right primitive here because the work is a blocked subprocess wait, not CPU.
    Results are returned in completion order; each is whatever launch_fn returns.
    """

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers

    def run(self, jobs: list[dict], launch_fn) -> list[dict]:
        results: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(launch_fn, job): job for job in jobs}
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())
        return results
```

> Keep the module header docstring; add a one-line note that the `Pool` wrapper is the Phase 2 addition and the rest is the promoted Phase 1 harness.

- [ ] **Step 4: Turn `tests/llm_harness.py` into a re-export shim**

Replace the entire contents of `mcp-server/tests/llm_harness.py` with:

```python
"""Back-compat shim. The harness now lives in the package at
agentic_mcp.headless (Phase 2 promoted it out of tests/ so the orchestrator can
import it at runtime). Existing e2e tests import from here unchanged.
"""
from agentic_mcp.headless import (  # noqa: F401
    ClaudeUnavailable,
    _claude_exe,
    _kill_tree,
    claude_on_path,
    result_text,
    run_claude_headless,
    stage_mcp_config,
)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_headless.py tests/test_llm_harness.py -v`
Expected: PASS (new Pool test + the existing harness unit tests via the shim)

- [ ] **Step 6: Commit**

```bash
git add mcp-server/src/agentic_mcp/headless.py mcp-server/tests/llm_harness.py mcp-server/tests/test_headless.py
git commit -m "refactor(headless): promote llm_harness to package + add Pool wrapper"
```

---

### Task 6: `scheduler.py` - ready-set + DAG merge order

**Goal:** Pure functions that compute which Tasks are ready to dispatch (deps resolved, parent Spec dispatched) and the topological order to merge completed worktree branches.

**Files:**
- Create: `mcp-server/src/agentic_mcp/scheduler.py`
- Test: `mcp-server/tests/test_scheduler.py`

**Acceptance Criteria:**
- [ ] `ready_tasks(conn)` returns Task nodes whose status is `pending`/`ready`, whose parent Spec (linked via the `implements` relation: Task implements Spec) is `dispatched`, and whose `depends-on` Tasks are all resolved.
- [ ] `merge_order(task_ids, edges)` returns a topological ordering honoring (task, dependency) edges; raises `ValueError` on a cycle.
- [ ] A Task with an unresolved `depends-on` dependency is excluded from `ready_tasks`.

> **Relation vocabulary (verified against `relations.py`):** the table is `relations` (plural). Valid relation types are `implements, depends-on, blocks, supersedes, caused-by, observed-in, touches, references, derived-from` - there is NO `belongs-to` or `blocked-by`. Use `implements` for Task->Spec and `depends-on` for Task->dependency. Use the `relations.neighbors(conn, node_id, relation_type, direction)` helper rather than raw SQL.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_scheduler.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_scheduler.py`:

```python
"""Ready-set computation + DAG merge ordering."""
import json

import pytest

from agentic_mcp import db, nodes, relations, scheduler


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def _dispatched_spec(conn):
    return nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
        feedback_loop="if a user reports a bug we open a PR and write a retro",
        dispatched_at="2026-05-23T00:00:00+00:00",
    )


def _task(conn, spec_id, status="pending"):
    tid = nodes.create_node(conn, "Task", status=status, owner="t", body="task")
    relations.link_nodes(conn, tid, spec_id, "implements")  # Task implements Spec
    return tid


def test_ready_excludes_blocked_tasks(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec)               # pending, no deps -> ready
        t2 = _task(conn, spec)               # depends-on t1 (pending) -> not ready
        relations.link_nodes(conn, t2, t1, "depends-on")
        ready_ids = {t["id"] for t in scheduler.ready_tasks(conn)}
        assert t1 in ready_ids
        assert t2 not in ready_ids
    finally:
        conn.close()


def test_ready_unblocks_after_dependency_resolved(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, status="done")
        t2 = _task(conn, spec)
        relations.link_nodes(conn, t2, t1, "depends-on")  # dep is done -> t2 ready
        ready_ids = {t["id"] for t in scheduler.ready_tasks(conn)}
        assert t2 in ready_ids
    finally:
        conn.close()


def test_merge_order_is_topological():
    # edges are (task, dependency): b depends-on a, c depends-on b
    order = scheduler.merge_order(["a", "b", "c"], [("b", "a"), ("c", "b")])
    assert order.index("a") < order.index("b") < order.index("c")


def test_merge_order_detects_cycle():
    with pytest.raises(ValueError):
        scheduler.merge_order(["a", "b"], [("a", "b"), ("b", "a")])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scheduler.py -v`
Expected: FAIL (`No module named 'agentic_mcp.scheduler'`)

- [ ] **Step 3: (Relation vocabulary already verified)**

Confirmed during planning against `relations.py`: table `relations` (plural); helper `relations.neighbors(conn, node_id, relation_type, direction)` returns the linked ids; valid types include `implements` and `depends-on` (NOT `belongs-to`/`blocked-by`). The implementation below uses the helper, so no raw SQL against the relations table.

- [ ] **Step 4: Implement `scheduler.py`**

Create `mcp-server/src/agentic_mcp/scheduler.py`:

```python
"""Stateless scheduling helpers for the orchestrator tick.

ready_tasks: Tasks eligible to dispatch now (parent Spec dispatched via the
'implements' relation, all 'depends-on' deps resolved). merge_order: topological
sort of completed tasks by (task, dependency) edges, used to merge worktree
branches into the integration branch in dependency order. Both are pure reads
over the graph - the orchestrator owns the side effects.
"""
from __future__ import annotations

import sqlite3

from . import nodes, relations

RESOLVED_STATUSES = {"done", "resolved", "merged", "closed"}
READY_STATUSES = {"pending", "ready"}


def _parent_spec_dispatched(conn: sqlite3.Connection, task_id: str) -> bool:
    # Task implements Spec (outgoing 'implements' relation).
    for sid in relations.neighbors(conn, task_id, "implements", direction="out"):
        spec = nodes.get_node(conn, sid)
        if spec and spec["type"] == "Spec" and spec["status"] == "dispatched":
            return True
    return False


def _deps_resolved(conn: sqlite3.Connection, task_id: str) -> bool:
    # Task depends-on its prerequisite Tasks (outgoing 'depends-on' relation).
    for dep_id in relations.neighbors(conn, task_id, "depends-on", direction="out"):
        dep = nodes.get_node(conn, dep_id)
        if dep is None or dep["status"] not in RESOLVED_STATUSES:
            return False
    return True


def ready_tasks(conn: sqlite3.Connection) -> list[dict]:
    out: list[dict] = []
    for (tid,) in conn.execute("SELECT id FROM task WHERE status IN ('pending','ready')"):
        if _parent_spec_dispatched(conn, tid) and _deps_resolved(conn, tid):
            out.append(nodes.get_node(conn, tid))
    return out


def merge_order(task_ids: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Topological order. *edges* are (task, blocked_by) pairs: task depends on
    blocked_by, so blocked_by must merge first."""
    deps: dict[str, set[str]] = {t: set() for t in task_ids}
    for task, blocker in edges:
        deps.setdefault(task, set()).add(blocker)
        deps.setdefault(blocker, set())
    ordered: list[str] = []
    done: set[str] = set()
    while len(ordered) < len(deps):
        progressed = False
        for t in deps:
            if t in done:
                continue
            if deps[t] <= done:
                ordered.append(t)
                done.add(t)
                progressed = True
        if not progressed:
            raise ValueError(f"cycle in merge graph among {set(deps) - done}")
    return ordered
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scheduler.py -v`
Expected: PASS. If a test errors on the `relation` table/column name, correct `_related_ids` to match `relations.py` (Step 3) and re-run.

- [ ] **Step 6: Commit**

```bash
git add mcp-server/src/agentic_mcp/scheduler.py mcp-server/tests/test_scheduler.py
git commit -m "feat(scheduler): ready-set computation + DAG merge ordering"
```

---

### Task 7: Orchestrator command + agent docs

**Goal:** Author `/agentic:orchestrate` (the single-tick driver) and `agents/orchestrator.md` (the scheduler role prompt), following the existing command/agent doc conventions and the agent-doc test contract.

**Files:**
- Create: `commands/orchestrate.md`
- Create: `agents/orchestrator.md`
- Test: `mcp-server/tests/test_agent_docs.py`

**Acceptance Criteria:**
- [ ] `agents/orchestrator.md` has the same frontmatter shape the other agent docs use, asserts `model: sonnet` (matching the test's existing expectation for agents), and documents that it implements nothing - it computes the DAG, detects overlap (via `detect_overlap`/`claim_scope`), weeds (`flag_stale`), calibrates (`record_outcome`/`adjust_trust`), and surfaces escalations.
- [ ] `commands/orchestrate.md` documents the single-tick contract: `--once` (default for `/loop`), `--pool N` (default 3), `--weed-days N` (default 14), hydrate-from-graph, dispatch headless workers/reviewers in worktrees, harvest, merge in DAG order, exit.
- [ ] `test_agent_docs.py` passes with the new agent included.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_agent_docs.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Read the existing conventions**

Read `agents/builder.md` and `agents/code-reviewer.md` for frontmatter shape and tone; read `commands/review-pr.md` and `commands/dispatch.md` for command-doc structure; read `mcp-server/tests/test_agent_docs.py` to see exactly what it asserts (frontmatter keys, `model: sonnet`, any required-substring checks).

- [ ] **Step 2: Write/adjust the failing test**

In `mcp-server/tests/test_agent_docs.py`, ensure the orchestrator is covered. If the test iterates a hardcoded list of agent files, add `"orchestrator.md"`; if it globs `agents/*.md`, it will pick it up automatically. Add a targeted assertion:

```python
def test_orchestrator_doc_declares_single_tick():
    from pathlib import Path
    text = Path(__file__).parents[2].joinpath("agents", "orchestrator.md").read_text(encoding="utf-8")
    assert "model: sonnet" in text
    assert "--once" in text
    assert "implements nothing" in text.lower()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_agent_docs.py::test_orchestrator_doc_declares_single_tick -v`
Expected: FAIL (file missing)

- [ ] **Step 4: Write `agents/orchestrator.md`**

Create `agents/orchestrator.md` with frontmatter matching the sibling agents (copy the exact key set from `builder.md`; set `model: sonnet`). Body must state: the orchestrator implements nothing; one stateless tick per invocation; hydrate all state from the graph; compute ready set + DAG; use `detect_overlap`/`claim_scope` for serial-when-shared; dispatch headless workers (`builder`) and reviewers (Phase-1 panel) into per-team worktrees; harvest structured results; merge clean branches in DAG order; run `flag_stale` weeding; update `record_outcome`/`adjust_trust`; surface conflicts/escalations to the user; honor `distrusted` roles by requiring a second reviewer. No cross-plugin references; concise tactical guidance only.

- [ ] **Step 5: Write `commands/orchestrate.md`**

Create `commands/orchestrate.md` following `review-pr.md` structure. Document: invocation `/agentic:orchestrate [--once] [--pool N] [--weed-days N]`; the 7-step tick (weed -> ready set -> overlap filter -> dispatch pool -> harvest -> calibrate -> exit); that `/loop` (or cron) owns cadence and each tick is a fresh, stateless process; auto-merge on reviewer-CLEAN, conflicts/escalations always surfaced; defaults pool=3, weed-days=14. ASCII only in any literal command strings.

- [ ] **Step 6: Run the agent-doc tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_agent_docs.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agents/orchestrator.md commands/orchestrate.md mcp-server/tests/test_agent_docs.py
git commit -m "feat(orchestrator): single-tick orchestrate command + orchestrator agent"
```

---

### Task 7.5: Orchestrator tick entry point (`orchestrate.py`)

**Goal:** Compose the Phase 2 components into one runnable, stateless tick — `tick()` wires weed -> ready-set -> overlap/claim -> headless `Pool` dispatch into worktrees -> harvest -> review -> DAG-ordered merge -> calibrate. All side-effecting steps are **seam-injectable** (default to real implementations; stubbed in fast tests) so the whole pipeline is deterministically testable without spawning `claude` or git. Add a `python -m agentic_mcp.orchestrate --once` CLI.

**Files:**
- Create: `mcp-server/src/agentic_mcp/orchestrate.py`
- Test: `mcp-server/tests/test_orchestrate.py`

**Design — `tick()` contract:**

```python
def tick(
    conn,
    *,
    repo: str = ".",
    pool_size: int = 3,
    weed_days: int = 14,
    launch_fn=...,        # job dict -> {"task_id","ok","sha"|"error"}; default wraps headless.run_claude_headless in try/except
    worktree_factory=..., # (repo, task_id) -> (worktree_path, branch_name); default: git worktree add
    merge_fn=...,         # (repo, branch) -> None (raises on conflict); default: git merge --no-ff
    review_fn=...,        # (conn, task_id, job_result) -> {"verdict":"CLEAN"|"NEEDS_FIXING","reviewer":role,"hit":bool}; default: dispatch headless reviewer
) -> dict
```

`tick()` returns a structured summary: `{"weeded":[ids], "dispatched":[ids], "merged":[ids], "failed":[ids], "escalations":[{task_id,error}], "calibrated":[roles]}`. It NEVER raises for normal worker/review/merge failures — those land in `failed`/`escalations`. It only propagates programming errors.

**Tick algorithm (the order is the contract):**
1. **Weed:** `result["weeded"] = weeding.flag_stale_specs(conn, weed_days)`.
2. **Ready set:** `ready = scheduler.ready_tasks(conn)`.
3. **Overlap filter:** build `candidates = [{"task_id": t["id"], "scope_paths": task_scope(t)} for t in ready]`; `batch = claims.detect_overlap(candidates)[:pool_size]`.
4. **Claim + worktree + jobs:** for each batched task: `worktree_factory(repo, tid)` -> `(wt, branch)`; `claims.claim_scope(conn, tid, scope_paths, worktree=wt, branch=branch)` (skip task on `ClaimConflict`); `nodes.update_node(conn, tid, status="in_progress")`; append job `{"task_id":tid,"worktree":wt,"branch":branch}`; remember `claim_id`.
5. **Dispatch pool:** `results = headless.Pool(max_workers=pool_size).run(jobs, launch_fn)` (empty list if no jobs).
6. **Review + calibrate:** for each `ok` job result, call `review_fn`; record the reviewer outcome via `calibration.record_outcome(conn, reviewer, hit)` then `calibration.adjust_trust(conn, reviewer)` (append reviewer to `result["calibrated"]` when `adjust_trust` reports `adjusted=True`). A `NEEDS_FIXING` verdict leaves the task `in_progress` and the claim held (it loops next tick); a `CLEAN` verdict proceeds to merge.
7. **Merge in DAG order:** compute `merge_order` over the CLEAN task ids using their `depends-on` edges (`_dep_edges(conn, ids)` built via `relations.neighbors(conn, tid, "depends-on", "out")` intersected with the CLEAN set); for each in order: `merge_fn(repo, branch)`; on success `nodes.update_node(conn, tid, status="merged")`, `claims.release_claim(conn, claim_id)`, append to `merged`; on exception append `{task_id,error}` to `escalations` and leave the claim held.
8. **Failures:** worker results with `ok=False` -> append `task_id` to `failed`, leave task `in_progress` + claim held for next-tick retry.
9. Return `result`.

`task_scope(task) -> list[str]`: convention — `task["tags"]` parsed as a JSON array of path globs; absent/unparseable -> `["**"]` (whole-repo, which overlaps everything and thus forces serial — the safe default).

**Default seam implementations (real):**
- `_real_launch(job)`: wraps `headless.run_claude_headless(prompt, cwd=job["worktree"], ...)` in try/except, returning `{"task_id":..,"ok":True,"sha":<git rev-parse HEAD in worktree>}` or `{"task_id":..,"ok":False,"error":str(e)}`. (This is the exception-catching `launch_fn` the `Pool` docstring requires.)
- `_real_worktree(repo, task_id)`: `git -C repo worktree add <path> -b <branch>`; returns `(path, branch)`. Use a deterministic path like `<repo>/.worktrees/<task_id>` and branch `orch/<task_id>`.
- `_real_merge(repo, branch)`: `git -C repo merge --no-ff <branch>`; raises `subprocess.CalledProcessError` on conflict (which step 7 catches into escalations).
- `_real_review(conn, task_id, job_result)`: dispatch a headless reviewer (Phase-1 panel) — for this task, a minimal default that returns `{"verdict":"CLEAN","reviewer":"code-reviewer","hit":True}` is acceptable IF clearly marked as the integration default that Task 8's e2e overrides with the real review path. (Keep the real reviewer dispatch thin; the heavy review logic lives in the existing `/agentic:review-pr` flow.)

**CLI:** `python -m agentic_mcp.orchestrate --once [--pool N] [--weed-days N] [--repo PATH]` opens the DB at `AGENTIC_DB_PATH` (reuse `server._db_path` logic or `db.connect`), calls `tick(...)` once, prints the JSON summary, exits 0. `--once` is accepted (and is currently the only mode; a bare invocation behaves the same — the flag exists for forward-compat and `/loop` clarity).

**Acceptance Criteria:**
- [ ] `tick()` with ALL seams stubbed runs the full pipeline against a staged graph and returns the structured summary — deterministic, no `claude`, no real git.
- [ ] Two non-overlapping ready Tasks (disjoint `tags` scopes) are BOTH dispatched and BOTH merged in one tick (stubbed seams); their claims end released and statuses `merged`.
- [ ] Two overlapping Tasks: only one is dispatched in the tick (serial-when-shared).
- [ ] A stubbed `launch_fn` returning `ok=False` for a task leaves it in `failed`, status `in_progress`, claim held.
- [ ] A stubbed `review_fn` returning a low-`hit` reviewer outcome drives `record_outcome` + (after enough misses) `adjust_trust`; the `calibrated` list reflects a fired adjustment.
- [ ] Merge order respects `depends-on` (a dependent task merges after its dependency).
- [ ] `python -m agentic_mcp.orchestrate --once` runs a tick against a temp DB and prints JSON (smoke test, stubbed or empty graph).

**Verify:** From `mcp-server/`: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -v` then `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`.

**Steps:** TDD — write `tests/test_orchestrate.py` first (stub every seam: `launch_fn`/`worktree_factory`/`merge_fn`/`review_fn` as in-memory fakes; build the graph with `nodes.create_node` + `relations.link_nodes` using `implements`/`depends-on`; assert the returned summary + resulting graph state). Confirm failure. Then implement `orchestrate.py`. Then the CLI smoke test. Commit `feat(orchestrate): stateless tick entry point composing the Phase 2 pipeline`.

> **Implementer note:** this is an integration task — favor clarity and the seam boundaries above all. Keep each seam's real implementation small; the point of the seams is that Task 8 swaps in the real `claude`/git path while the fast tests use fakes. Do NOT spawn real `claude` or create real worktrees in `tests/test_orchestrate.py`.

---

### Task 8: Phase 2 LLM e2e exit-gate test

**Goal:** The exit gate, behind the `llm` marker: two orthogonal Specs build in parallel into separate worktrees and merge without collision; weeding surfaces a deliberately-stale node; a scripted reviewer miss drives `adjust_trust` to fire and the next tick honors the distrust flag.

**Files:**
- Create: `mcp-server/tests/test_phase2_e2e.py`
- Reference (read, don't modify): `mcp-server/tests/test_phase1_e2e.py` for the staging pattern (`stage_mcp_config`, `--mcp-config`, temp project, fixtures)

**Acceptance Criteria:**
- [ ] Test is marked `@pytest.mark.llm` and `@pytest.mark.skipif(not headless.claude_on_path())`.
- [ ] Parallel scenario: two Specs with disjoint `scope_paths` are dispatched; the orchestrator pool builds both in separate worktrees; both branches merge to the integration branch with no conflict; both Specs' criteria end satisfied.
- [ ] Weeding scenario: a node with an old `last_touched` is surfaced by `flag_stale_specs` on a tick.
- [ ] Calibration scenario: a scripted reviewer miss (a stability contradiction) is recorded via `record_outcome`, `adjust_trust` returns `adjusted=True` with `distrusted=1`, and a follow-up scheduling read shows the second-reviewer requirement honored.
- [ ] Deselected by default (`-m "not llm"`); runs only under `-m llm`.

**Verify:** `./.venv/Scripts/python.exe -m pytest -m llm tests/test_phase2_e2e.py -v` (requires live `claude`) -> pass; and `./.venv/Scripts/python.exe -m pytest -m "not llm" -q` still deselects it.

**Steps:**

- [ ] **Step 1: Study the Phase 1 e2e staging**

Read `test_phase1_e2e.py` end to end. Reuse its temp-project setup, `headless.stage_mcp_config(project, db_path)`, and `headless.run_claude_headless(prompt, cwd=project, mcp_config=cfg)` calls. Reuse fixtures under `tests/fixtures/`.

- [ ] **Step 2: Write the calibration + weeding portions first (deterministic, no live agent)**

These two scenarios can be asserted against the modules directly (no `claude` needed) but live in the e2e file so the gate is one place. Write them with real fixtures:

```python
import json
import pytest

from agentic_mcp import db, nodes, calibration, weeding, headless

pytestmark = pytest.mark.llm


def test_calibration_adjustment_fires(tmp_path):
    p = tmp_path / "graph.db"
    db.init_db(p)
    conn = db.connect(p)
    try:
        for _ in range(8):
            calibration.record_outcome(conn, "code-reviewer", hit=False)
        res = calibration.adjust_trust(conn, "code-reviewer")
        assert res["adjusted"] and res["distrusted"] == 1
    finally:
        conn.close()


def test_weeding_surfaces_stale_spec(tmp_path):
    from datetime import datetime, timedelta, timezone
    p = tmp_path / "graph.db"
    db.init_db(p)
    conn = db.connect(p)
    try:
        sid = nodes.create_node(
            conn, "Spec", status="dispatched", owner="t", body="s",
            criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
            feedback_loop="if a user reports a bug we open a PR and write a retro",
        )
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
        conn.execute("UPDATE spec SET last_touched=? WHERE id=?", (old, sid))
        conn.commit()
        assert sid in weeding.flag_stale_specs(conn, days=14)
    finally:
        conn.close()
```

- [ ] **Step 3: Write the parallel-build scenario (live agent)**

Add the headless two-team scenario. Stage a temp project + `.mcp.json`, create two Specs whose `claim_scope` paths are disjoint, then drive `/agentic:orchestrate --once --pool 2` via `run_claude_headless` (prompt instructs the orchestrator to run one tick against the staged graph). Assert: two worktree branches were created, both merged to the integration branch (`git log` shows both commits, no merge-conflict markers), and both Specs' criteria are marked satisfied in the graph. Use a generous `timeout` (e.g. 1800) given two builds run.

> Keep the live portion resilient: if `headless.claude_on_path()` is False, the `skipif` skips the whole module. Assert on structured graph state and `git` output, never on raw agent prose (mirrors the Phase 1 e2e discipline).

- [ ] **Step 4: Verify default-deselect + marker**

Run: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: the Phase 2 e2e is deselected (count unchanged from Task 6's run).

Run (live): `./.venv/Scripts/python.exe -m pytest -m llm tests/test_phase2_e2e.py -v`
Expected: PASS against a live `claude` session.

- [ ] **Step 5: Commit**

```bash
git add mcp-server/tests/test_phase2_e2e.py
git commit -m "test(e2e): Phase 2 exit gate - parallel build, weeding, calibration adjustment"
```

---

### Task 9: Docs - README + router skill + spec status

**Goal:** Update the user-facing docs to reflect Phase 2: the new command/agent surface, the 25-tool count, the new tools' purpose, and mark the design spec status complete.

**Files:**
- Modify: `README.md`
- Modify: `skills/router/SKILL.md`
- Modify: `docs/superpowers/specs/2026-05-23-phase-2-orchestration-design.md` (status line)

**Acceptance Criteria:**
- [ ] README has a "Phase 2: Orchestration & Parallelism" section listing `/agentic:orchestrate`, the orchestrator agent, the 7 new tools, and the exit gate; tool-count references updated 18 -> 25.
- [ ] `skills/router/SKILL.md` documents the 7 new tools alongside the Phase 0/1 sets.
- [ ] No test asserts a stale tool count (grep for `18` / `"18 tools"` and update narrative references; the authoritative count assertion lives in `test_server.py` from Task 4).

**Verify:** `./.venv/Scripts/python.exe -m pytest -m "not llm" -q` -> all pass (docs change shouldn't break tests; this confirms no count assertions regressed)

**Steps:**

- [ ] **Step 1: Update README**

Add a "## Phase 2: Orchestration & Parallelism" section after the Phase 1 section: describe the stateless single-tick orchestrator, headless worker/reviewer pool, worktree isolation, serial-when-shared claims, scheduled weeding, trust-weighting calibration. Add the 7 tools to the "MCP tool surface" section and change the heading count to **25 tools**. Update the "Phase 1 total: 18" line and any "18 tools" mentions to reflect Phase 2 = 25.

- [ ] **Step 2: Update the router skill**

In `skills/router/SKILL.md`, add a Phase 2 tool block documenting `claim_scope`, `release_claim`, `detect_overlap`, `flag_stale`, `record_outcome`, `get_calibration`, `adjust_trust`.

- [ ] **Step 3: Mark the design spec complete**

In `docs/superpowers/specs/2026-05-23-phase-2-orchestration-design.md`, change the status line to `**Status:** Implemented (Phase 2)`.

- [ ] **Step 4: Run the fast suite**

Run: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add README.md skills/router/SKILL.md docs/superpowers/specs/2026-05-23-phase-2-orchestration-design.md
git commit -m "docs(phase2): README + router tool surface (25 tools); spec status complete"
```

---

## Self-Review

**Spec coverage:**
- Runtime topology / single-tick stateless orchestrator -> Tasks 7 (command/agent) + 6 (scheduler) + 5 (Pool).
- Execution engine (promote `llm_harness.py` + Pool) -> Task 5.
- Graph additions (claim, calibration, stale_flagged_at, v3 migration) -> Task 0.
- 7 new MCP tools -> Tasks 1/2/3 (logic) + 4 (registration).
- Serial-when-shared / claim overlap -> Task 1.
- Weeding + stale-spec -> Task 2.
- Trust-weighting calibration -> Task 3.
- DAG ordering -> Task 6.
- Testing (fast unit + llm e2e exit gate) -> per-task tests + Task 8.
- Defaults (pool 3, weed 14, auto-merge, surface escalations) -> Tasks 7 + 8.
- Docs -> Task 9.
All design sections map to a task. No gaps.

**Placeholder scan:** All code steps contain runnable code. Task 7 (doc-authoring) and Task 8 step 3 (live-agent scenario) describe required *content/assertions* rather than a fixed code block, because they author prose docs / a live-CLI test whose exact prompt text is environment-dependent; both list concrete required substrings and assertions so they are verifiable, not vague.

**Type/name consistency:** `claim_scope`/`release_claim`/`detect_overlap` (claims.py) used identically in Task 4 server dispatch. `record_outcome`/`get_calibration`/`adjust_trust` (calibration.py) consistent across Tasks 3/4/8. `flag_stale_specs` (weeding.py) is the function; the MCP tool name is `flag_stale` (mapped in Task 4) - intentional and consistent. `ready_tasks`/`merge_order` (scheduler.py) consistent. `Pool.run(jobs, launch_fn)` consistent Tasks 5/8. `headless.claude_on_path` used in Task 8 skipif matches the promoted function name.

**Relation vocabulary verified:** Task 6 originally assumed `belongs-to`/`blocked-by` relations and a `relation` table. Reading `relations.py` during planning corrected this: the table is `relations` (plural), the valid vocabulary is `implements`/`depends-on`/`blocks`/... (no `belongs-to`/`blocked-by`), and there is a `neighbors(conn, node_id, relation_type, direction)` helper. Task 6's tests and implementation now use `implements` (Task->Spec), `depends-on` (Task->dependency), and the `neighbors` helper - no assumed names remain.

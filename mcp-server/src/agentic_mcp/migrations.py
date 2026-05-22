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
PHASE_2_VERSION = 2
SCHEMA_VERSION = PHASE_2_VERSION

# SQLite cannot ALTER a CHECK constraint, so widening the retro.failed_layer
# domain (adding 'integration') requires the documented 12-step table rebuild:
# create the replacement, copy rows with an explicit column list, drop the old
# table, rename. retro carries no indexes or foreign keys, so nothing else needs
# rebuilding. Idempotent: re-running it against the already-widened table just
# copies the same rows back.
_RETRO_REBUILD_DDL = """
CREATE TABLE retro_new (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Retro'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  failed_layer TEXT CHECK(failed_layer IN ('spec','implementation','integration','review','unknowable'))
);
INSERT INTO retro_new
  SELECT id, type, status, severity, owner, created_at, last_touched,
         body, summary, tags, scope, failed_layer
  FROM retro;
DROP TABLE retro;
ALTER TABLE retro_new RENAME TO retro;
"""

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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _add_column_if_missing(conn, table: str, col: str, decl: str) -> None:
    if not _table_exists(conn, table):
        return  # table will be created by schema.sql; skip ALTER
    if col not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _migrate_to_phase_1(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "spec", "dispatched_at", "TEXT")
    _add_column_if_missing(conn, "finding", "criterion_index", "INTEGER")
    _add_column_if_missing(conn, "finding", "loop_iteration", "INTEGER")
    _add_column_if_missing(
        conn, "finding", "triage",
        "TEXT CHECK(triage IN ('fix-in-pr','backlog'))",
    )
    conn.executescript(_CRITICAL_LOOP_DDL)


def _migrate_to_phase_2(conn: sqlite3.Connection) -> None:
    # Widen retro.failed_layer to admit the 'integration' layer. retro always
    # exists here (apply_migrations guards on the spec table, and retro ships in
    # the same Phase 0 schema.sql).
    conn.executescript(_RETRO_REBUILD_DDL)


def apply_migrations(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    # If the Phase 0 base tables haven't been created yet (empty file being
    # opened by connect() before schema.sql runs), there is nothing to migrate.
    # init_db() will call us again after executing schema.sql.
    if not _table_exists(conn, "spec"):
        return
    if version < PHASE_1_VERSION:
        _migrate_to_phase_1(conn)
    if version < PHASE_2_VERSION:
        _migrate_to_phase_2(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()

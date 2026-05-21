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


def apply_migrations(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] >= PHASE_1_VERSION:
        return
    # If the Phase 0 base tables haven't been created yet (empty file being
    # opened by connect() before schema.sql runs), there is nothing to migrate.
    # init_db() will call us again after executing schema.sql.
    if not _table_exists(conn, "spec"):
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

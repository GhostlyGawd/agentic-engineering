"""SQLite connection and schema management.

Phase 0 uses plain SQLite (no extensions). sqlite-vec and the vec0 virtual table
are deferred to Phase 3 when pattern-finder needs vector search.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from . import migrations

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection. Caller manages close()."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    # Cross-process contention is now by-design (the supervisor's tick
    # connections vs the HUD's read connections). Wait on a held lock instead
    # of failing fast with 'database is locked'. (Python's sqlite3 already
    # defaults timeout=5.0s, but we set it explicitly so the intent is durable.)
    conn.execute("PRAGMA busy_timeout = 5000")
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


def resolve_db_path() -> Path:
    """Resolve AGENTIC_DB_PATH (default ./.agentic/graph.db); init if missing.

    Single owner for the server CLI and the orchestrate CLI (both opened the DB
    the same way; this de-duplicates that logic).
    """
    raw = os.environ.get("AGENTIC_DB_PATH", "./.agentic/graph.db")
    p = Path(raw).resolve()
    if not p.exists():
        init_db(p)
    return p

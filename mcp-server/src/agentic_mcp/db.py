"""SQLite connection and schema management.

Phase 0 uses plain SQLite (no extensions). sqlite-vec and the vec0 virtual table
are deferred to Phase 3 when pattern-finder needs vector search.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection. Caller manages close()."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
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
    finally:
        conn.close()

"""Ephemeral supervisor runtime state (~/.agentic/supervisor.db).

Holds ONLY: per-(project,tick) last_run + last_outcome + last_pid, a single
heartbeat row, and runtime pause flags. NO durable project data lives here -- if
deleted, the daemon rebuilds it (worst case: a tick fires early). Created on the
fly with CREATE TABLE IF NOT EXISTS (no migration framework).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS tick_state (
  project TEXT NOT NULL,
  tick TEXT NOT NULL,
  last_run TEXT,
  last_outcome TEXT,
  last_pid INTEGER,
  PRIMARY KEY (project, tick)
);
CREATE TABLE IF NOT EXISTS heartbeat (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  beat_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paused (
  project TEXT PRIMARY KEY
);
"""


def default_state_path() -> Path:
    raw = os.environ.get("AGENTIC_SUPERVISOR_DB")
    if raw:
        return Path(raw).resolve()
    return (Path.home() / ".agentic" / "supervisor.db").resolve()


def connect_state(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_DDL)
    conn.commit()
    return conn


def record_run(conn, project: str, tick: str, last_run: str, outcome: str,
               pid: int | None = None) -> None:
    conn.execute(
        "INSERT INTO tick_state(project, tick, last_run, last_outcome, last_pid) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(project, tick) DO UPDATE SET "
        "last_run=excluded.last_run, last_outcome=excluded.last_outcome, "
        "last_pid=excluded.last_pid",
        (project, tick, last_run, outcome, pid),
    )
    conn.commit()


def get_last_run(conn, project: str, tick: str) -> str | None:
    row = conn.execute(
        "SELECT last_run FROM tick_state WHERE project=? AND tick=?",
        (project, tick),
    ).fetchone()
    return row[0] if row else None


def all_state(conn) -> list[dict]:
    cols = ["project", "tick", "last_run", "last_outcome", "last_pid"]
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT project, tick, last_run, last_outcome, last_pid FROM tick_state "
        "ORDER BY project, tick")]


def beat(conn, beat_at: str) -> None:
    conn.execute(
        "INSERT INTO heartbeat(id, beat_at) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET beat_at=excluded.beat_at",
        (beat_at,),
    )
    conn.commit()


def last_beat(conn) -> str | None:
    row = conn.execute("SELECT beat_at FROM heartbeat WHERE id=1").fetchone()
    return row[0] if row else None


def set_paused(conn, project: str) -> None:
    conn.execute("INSERT OR IGNORE INTO paused(project) VALUES (?)", (project,))
    conn.commit()


def clear_paused(conn, project: str) -> None:
    conn.execute("DELETE FROM paused WHERE project=?", (project,))
    conn.commit()


def is_paused(conn, project: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM paused WHERE project=?", (project,)
    ).fetchone() is not None

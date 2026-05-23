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

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

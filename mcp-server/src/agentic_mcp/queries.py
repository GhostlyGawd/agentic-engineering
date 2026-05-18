"""Read paths over the graph."""
from __future__ import annotations

import json
import sqlite3
from collections import deque

from .nodes import ENTITY_TABLES, get_node


def query_graph(
    conn: sqlite3.Connection,
    type: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    scope: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return matching nodes across one or all entity tables.

    If `type` is given, query only that table. Else union across all tables.
    """
    tables = [ENTITY_TABLES[type]] if type else list(ENTITY_TABLES.values())
    results: list[dict] = []
    for t in tables:
        clauses = []
        params: list = []
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if severity is not None:
            clauses.append("severity=?")
            params.append(severity)
        if scope is not None:
            clauses.append("scope=?")
            params.append(scope)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM {t} {where} ORDER BY last_touched DESC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            results.append(dict(zip(cols, row)))
        if len(results) >= limit:
            return results[:limit]
    return results[:limit]


def get_required_reads(conn: sqlite3.Connection, spec_id: str) -> list[dict]:
    spec = get_node(conn, spec_id)
    if spec is None or spec["type"] != "Spec":
        return []
    raw = spec.get("required_reads")
    if not raw:
        return []
    try:
        ids = json.loads(raw)
    except (ValueError, TypeError):
        return []
    out = []
    for nid in ids:
        n = get_node(conn, nid)
        if n is not None:
            out.append(n)
    return out


def walk_down(
    conn: sqlite3.Connection, root_id: str, max_depth: int = 3
) -> list[dict]:
    """BFS over inbound 'implements' / 'depends-on' edges (children point at parent)."""
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(root_id, 0)])
    out: list[dict] = []
    while queue:
        nid, depth = queue.popleft()
        if depth >= max_depth:
            continue
        rows = conn.execute(
            "SELECT from_id FROM relations WHERE to_id=? AND relation_type IN ('implements','depends-on')",
            (nid,),
        ).fetchall()
        for (child_id,) in rows:
            if child_id in seen:
                continue
            seen.add(child_id)
            node = get_node(conn, child_id)
            if node is not None:
                out.append(node)
                queue.append((child_id, depth + 1))
    return out

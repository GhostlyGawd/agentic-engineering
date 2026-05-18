"""Typed-relation CRUD over the graph DB."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

VALID_RELATIONS = {
    "implements", "depends-on", "blocks", "supersedes",
    "caused-by", "observed-in", "touches", "references", "derived-from",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def link_nodes(conn: sqlite3.Connection, from_id: str, to_id: str, relation_type: str) -> None:
    if relation_type not in VALID_RELATIONS:
        raise ValueError(
            f"unknown relation type: {relation_type!r}. "
            f"Valid: {sorted(VALID_RELATIONS)}"
        )
    try:
        conn.execute(
            "INSERT INTO relations(from_id, to_id, relation_type, created_at) VALUES (?,?,?,?)",
            (from_id, to_id, relation_type, _now()),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        # PRIMARY KEY collision = already linked; swallow for idempotency.
        if "UNIQUE" in str(e) or "PRIMARY KEY" in str(e):
            return
        raise


def neighbors(
    conn: sqlite3.Connection,
    node_id: str,
    relation_type: str | None = None,
    direction: str = "out",
) -> list[str]:
    if direction == "out":
        col, target = "from_id", "to_id"
    elif direction == "in":
        col, target = "to_id", "from_id"
    else:
        raise ValueError(f"direction must be 'in' or 'out', got {direction!r}")

    if relation_type is not None:
        rows = conn.execute(
            f"SELECT {target} FROM relations WHERE {col}=? AND relation_type=?",
            (node_id, relation_type),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {target} FROM relations WHERE {col}=?", (node_id,)
        ).fetchall()
    return [r[0] for r in rows]

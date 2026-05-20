"""Typed entity CRUD over the graph DB."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

ENTITY_TABLES = {
    "Goal": "goal",
    "Epic": "epic",
    "Task": "task",
    "Subtask": "subtask",
    "Spec": "spec",
    "Decision": "decision",
    "Bug": "bug",
    "Finding": "finding",
    "Pattern": "pattern",
    "Module": "module",
    "File": "file",
    "Review": "review",
    "Retro": "retro",
    "ArchDebt": "arch_debt",
    "CriticalLoop": "critical_loop",
}

# Required fields beyond the auto-filled ones (id, created_at, last_touched, type).
BASE_REQUIRED = {"status", "owner", "body"}

# Type-specific extra required fields.
EXTRA_REQUIRED = {
    "Spec": {"criteria_json", "feedback_loop"},
    "Finding": {"severity", "parent_id"},
    "File": {"path"},
    "CriticalLoop": {"finding_id", "started_at"},
}

# Optional type-specific columns (allowed but not required).
EXTRA_OPTIONAL = {
    "Spec": {"required_reads", "dispatched_at"},
    "Finding": {"subtype"},
    "Retro": {"failed_layer"},
    "Review": {"verdict"},
    "CriticalLoop": {"iteration_count", "diagnostic_fired_at", "resolved_at"},
}

# Columns common to all entity tables.
COMMON_COLS = (
    "id", "type", "status", "severity", "owner",
    "created_at", "last_touched", "body", "summary", "tags", "scope",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table_for(ntype: str) -> str:
    try:
        return ENTITY_TABLES[ntype]
    except KeyError:
        raise ValueError(f"unknown entity type: {ntype}")


def _all_cols_for(ntype: str) -> tuple[str, ...]:
    extras = EXTRA_REQUIRED.get(ntype, set()) | EXTRA_OPTIONAL.get(ntype, set())
    return COMMON_COLS + tuple(sorted(extras))


def create_node(conn: sqlite3.Connection, type: str, **fields) -> str:
    table = _table_for(type)
    required = BASE_REQUIRED | EXTRA_REQUIRED.get(type, set())
    missing = required - fields.keys()
    if missing:
        raise ValueError(f"missing required field(s) for {type}: {sorted(missing)}")

    nid = fields.pop("id", None) or uuid.uuid4().hex
    now = _now()
    cols = _all_cols_for(type)
    values = {
        "id": nid,
        "type": type,
        "created_at": now,
        "last_touched": now,
        "severity": fields.get("severity"),
        "summary": fields.get("summary"),
        "tags": fields.get("tags"),
        "scope": fields.get("scope"),
    }
    for k, v in fields.items():
        if k in cols:
            values[k] = v
    # Status and body always present (required-check above).
    values["status"] = fields["status"]
    values["body"] = fields["body"]
    values["owner"] = fields["owner"]

    use_cols = [c for c in cols if c in values]
    placeholders = ",".join("?" for _ in use_cols)
    col_list = ",".join(use_cols)
    conn.execute(
        f"INSERT INTO {table}({col_list}) VALUES ({placeholders})",
        [values[c] for c in use_cols],
    )
    conn.commit()
    return nid


def update_node(conn: sqlite3.Connection, id: str, **fields) -> None:
    row = get_node(conn, id)
    if row is None:
        raise ValueError(f"no such node: {id}")
    table = _table_for(row["type"])
    fields["last_touched"] = _now()
    cols = _all_cols_for(row["type"])
    use = {k: v for k, v in fields.items() if k in cols and k not in ("id", "type", "created_at")}
    if not use:
        return
    set_clause = ",".join(f"{k}=?" for k in use)
    conn.execute(f"UPDATE {table} SET {set_clause} WHERE id=?", [*use.values(), id])
    conn.commit()


def get_node(conn: sqlite3.Connection, id: str) -> dict | None:
    for ntype, table in ENTITY_TABLES.items():
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone()
        if row is not None:
            cols = [d[0] for d in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
            return dict(zip(cols, row))
    return None

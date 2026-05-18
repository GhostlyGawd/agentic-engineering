"""High-level convenience writes: log_finding and mark_criterion_satisfied."""
from __future__ import annotations

import json
import sqlite3

from . import nodes

VALID_SEVERITIES = {"Critical", "Important", "Suggested", "Strength"}


def log_finding(
    conn: sqlite3.Connection,
    parent_id: str,
    severity: str,
    body: str,
    subtype: str | None = None,
    scope: str | None = None,
    owner: str = "system",
) -> str:
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"unknown severity: {severity!r}. Valid: {sorted(VALID_SEVERITIES)}"
        )
    parent = nodes.get_node(conn, parent_id)
    if parent is None:
        raise ValueError(f"parent node not found: {parent_id}")
    if scope is None:
        scope = parent.get("scope")
    fields = dict(
        status="open", owner=owner, body=body,
        severity=severity, parent_id=parent_id, scope=scope,
    )
    if subtype is not None:
        fields["subtype"] = subtype
    return nodes.create_node(conn, "Finding", **fields)


def mark_criterion_satisfied(
    conn: sqlite3.Connection, spec_id: str, criterion_index: int, evidence: str
) -> None:
    if not evidence or not evidence.strip():
        raise ValueError("evidence is required (non-empty)")
    spec = nodes.get_node(conn, spec_id)
    if spec is None or spec["type"] != "Spec":
        raise ValueError(f"not a Spec node: {spec_id}")
    criteria = json.loads(spec["criteria_json"])
    if criterion_index < 0 or criterion_index >= len(criteria):
        raise IndexError(
            f"criterion_index {criterion_index} out of range "
            f"(spec has {len(criteria)} criteria)"
        )
    criteria[criterion_index]["satisfied"] = True
    criteria[criterion_index]["evidence"] = evidence.strip()
    nodes.update_node(conn, spec_id, criteria_json=json.dumps(criteria))

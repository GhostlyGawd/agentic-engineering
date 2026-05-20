"""High-level convenience writes: log_finding and mark_criterion_satisfied."""
from __future__ import annotations

import json
import sqlite3

from . import nodes

VALID_SEVERITIES = {"Critical", "Important", "Suggested", "Strength"}
VALID_TRIAGE = {"fix-in-pr", "backlog"}


def log_finding(
    conn: sqlite3.Connection,
    parent_id: str,
    severity: str,
    body: str,
    subtype: str | None = None,
    scope: str | None = None,
    owner: str = "system",
    criterion_index: int | None = None,
    loop_iteration: int | None = None,
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
    if criterion_index is not None:
        fields["criterion_index"] = criterion_index
    if loop_iteration is not None:
        fields["loop_iteration"] = loop_iteration
    return nodes.create_node(conn, "Finding", **fields)


def record_triage(conn: sqlite3.Connection, finding_id: str, decision: str) -> None:
    """Set the triage decision on an Important finding (design L-9 / section 7)."""
    if decision not in VALID_TRIAGE:
        raise ValueError(
            f"unknown triage decision: {decision!r}. Valid: {sorted(VALID_TRIAGE)}"
        )
    finding = nodes.get_node(conn, finding_id)
    if finding is None or finding["type"] != "Finding":
        raise ValueError(f"not a Finding node: {finding_id}")
    if finding["severity"] != "Important":
        raise ValueError(
            f"triage applies only to Important findings; {finding_id} is "
            f"{finding['severity']!r}"
        )
    nodes.update_node(conn, finding_id, triage=decision)


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

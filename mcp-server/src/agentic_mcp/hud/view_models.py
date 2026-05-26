"""Pure render models for the HUD. NO textual import. Built only on the existing
read helpers -- this module never reimplements DB access and never writes."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from .. import nodes, queries, relations

_BOARD_LEVELS = ("Goal", "Epic", "Task", "Subtask")


@dataclass
class BoardItem:
    node: dict
    children: list["BoardItem"] = field(default_factory=list)


@dataclass
class BoardModel:
    goals: list[BoardItem]
    by_level: dict[str, list[dict]]


@dataclass
class SignalsModel:
    patterns: list[dict]
    arch_debt: list[dict]
    findings: list[dict]
    calibration: list[dict]


@dataclass
class TaskSheetModel:
    task: dict
    spec: dict | None
    criteria: list
    origin_signal: dict | None
    parent: dict | None
    reviews: list[dict]


def _children_items(conn: sqlite3.Connection, parent_id: str) -> list[BoardItem]:
    # Children point AT the parent via 'implements' (from_id=child, to_id=parent).
    child_ids = relations.neighbors(conn, parent_id, relation_type="implements",
                                    direction="in")
    items = []
    for cid in child_ids:
        node = nodes.get_node(conn, cid)
        if node is None:
            continue
        items.append(BoardItem(node=node, children=_children_items(conn, cid)))
    return items


def board_view(conn: sqlite3.Connection) -> BoardModel:
    goals = [BoardItem(node=g, children=_children_items(conn, g["id"]))
             for g in queries.query_graph(conn, type="Goal", limit=200)]
    by_level = {lvl: queries.query_graph(conn, type=lvl, limit=500)
                for lvl in _BOARD_LEVELS}
    return BoardModel(goals=goals, by_level=by_level)


def _in_neighbors_of_type(conn, node_id, ntype):
    out = []
    for nid in relations.neighbors(conn, node_id, direction="in"):
        n = nodes.get_node(conn, nid)
        if n is not None and n["type"] == ntype:
            out.append(n)
    return out


def signals_view(conn: sqlite3.Connection) -> SignalsModel:
    patterns = queries.query_graph(conn, type="Pattern", limit=100)
    try:
        arch_debt = queries.query_graph(conn, type="ArchDebt", limit=100)
    except (sqlite3.OperationalError, KeyError):
        arch_debt = []
    findings = [f for f in queries.query_graph(conn, type="Finding", limit=200)
                if f.get("triage") == "backlog"]
    calibration: list[dict] = []
    try:
        roles = [r[0] for r in conn.execute("SELECT role FROM calibration")]
        from .. import calibration as cal
        calibration = [cal.get_calibration(conn, role) for role in roles]
        calibration.sort(key=lambda c: (0 if c.get("distrusted") else 1, c.get("score", 1.0)))
    except sqlite3.OperationalError:
        calibration = []
    return SignalsModel(patterns=patterns, arch_debt=arch_debt,
                        findings=findings, calibration=calibration)


def task_sheet_view(conn: sqlite3.Connection, task_id: str) -> TaskSheetModel:
    task = nodes.get_node(conn, task_id)
    specs = _in_neighbors_of_type(conn, task_id, "Spec")
    spec = specs[0] if specs else None
    criteria: list = []
    if spec and spec.get("criteria_json"):
        try:
            criteria = json.loads(spec["criteria_json"])
        except (ValueError, TypeError):
            criteria = []
    origin_ids = relations.neighbors(conn, task_id, relation_type="derived-from",
                                     direction="out")
    origin_signal = nodes.get_node(conn, origin_ids[0]) if origin_ids else None
    parent_ids = relations.neighbors(conn, task_id, relation_type="implements",
                                     direction="out")
    parent = nodes.get_node(conn, parent_ids[0]) if parent_ids else None
    reviews = _in_neighbors_of_type(conn, task_id, "Review")
    return TaskSheetModel(task=task, spec=spec, criteria=criteria,
                          origin_signal=origin_signal, parent=parent, reviews=reviews)


def overview_counts(conn: sqlite3.Connection) -> dict:
    gated = queries.query_graph(conn, type="Task", status="awaiting_approval", limit=500)
    escalated = queries.query_graph(conn, type="Task", status="escalated", limit=500)
    tasks = queries.query_graph(conn, type="Task", limit=1)
    last_activity = tasks[0]["last_touched"] if tasks else None
    return {"gated_count": len(gated), "escalation_count": len(escalated),
            "last_activity": last_activity}

"""Stateless scheduling helpers for the orchestrator tick.

ready_tasks: Tasks eligible to dispatch now (parent Spec dispatched via the
'implements' relation, all 'depends-on' deps resolved). merge_order: topological
sort of completed tasks by (task, dependency) edges, used to merge worktree
branches into the integration branch in dependency order. Both are pure reads
over the graph - the orchestrator owns the side effects.
"""
from __future__ import annotations

import sqlite3

from . import nodes, relations

RESOLVED_STATUSES = {"done", "resolved", "merged", "closed"}
READY_STATUSES = {"pending", "ready"}


def _parent_spec_dispatched(conn: sqlite3.Connection, task_id: str) -> bool:
    # Task implements Spec (outgoing 'implements' relation).
    for sid in relations.neighbors(conn, task_id, "implements", direction="out"):
        spec = nodes.get_node(conn, sid)
        if spec and spec["type"] == "Spec" and spec["status"] == "dispatched":
            return True
    return False


def _deps_resolved(conn: sqlite3.Connection, task_id: str) -> bool:
    # Task depends-on its prerequisite Tasks (outgoing 'depends-on' relation).
    for dep_id in relations.neighbors(conn, task_id, "depends-on", direction="out"):
        dep = nodes.get_node(conn, dep_id)
        if dep is None or dep["status"] not in RESOLVED_STATUSES:
            return False
    return True


def ready_tasks(conn: sqlite3.Connection) -> list[dict]:
    placeholders = ",".join("?" * len(READY_STATUSES))
    out: list[dict] = []
    for (tid,) in conn.execute(
        f"SELECT id FROM task WHERE status IN ({placeholders})",
        tuple(sorted(READY_STATUSES)),
    ):
        if _parent_spec_dispatched(conn, tid) and _deps_resolved(conn, tid):
            out.append(nodes.get_node(conn, tid))
    return out


def merge_order(task_ids: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Topological order. *edges* are (task, blocked_by) pairs: task depends on
    blocked_by, so blocked_by must merge first."""
    deps: dict[str, set[str]] = {t: set() for t in task_ids}
    for task, blocker in edges:
        deps.setdefault(task, set()).add(blocker)
        deps.setdefault(blocker, set())
    ordered: list[str] = []
    done: set[str] = set()
    # O(n^2) worst case (re-scans nodes each pass); fine at tick-scale DAG sizes
    # (tens of tasks). Revisit with Kahn + indegree map if batches grow large.
    while len(ordered) < len(deps):
        progressed = False
        for t in deps:
            if t in done:
                continue
            if deps[t] <= done:
                ordered.append(t)
                done.add(t)
                progressed = True
        if not progressed:
            raise ValueError(f"cycle in merge graph among {set(deps) - done}")
    return ordered

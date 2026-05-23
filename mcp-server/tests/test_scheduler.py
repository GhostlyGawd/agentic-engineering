"""Ready-set computation + DAG merge ordering."""
import json

import pytest

from agentic_mcp import db, nodes, relations, scheduler


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def _dispatched_spec(conn):
    return nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
        feedback_loop="if a user reports a bug we open a PR and write a retro",
        dispatched_at="2026-05-23T00:00:00+00:00",
    )


def _task(conn, spec_id, status="pending"):
    tid = nodes.create_node(conn, "Task", status=status, owner="t", body="task")
    relations.link_nodes(conn, tid, spec_id, "implements")  # Task implements Spec
    return tid


def test_ready_excludes_blocked_tasks(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec)               # pending, no deps -> ready
        t2 = _task(conn, spec)               # depends-on t1 (pending) -> not ready
        relations.link_nodes(conn, t2, t1, "depends-on")
        ready_ids = {t["id"] for t in scheduler.ready_tasks(conn)}
        assert t1 in ready_ids
        assert t2 not in ready_ids
    finally:
        conn.close()


def test_ready_unblocks_after_dependency_resolved(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, status="done")
        t2 = _task(conn, spec)
        relations.link_nodes(conn, t2, t1, "depends-on")  # dep is done -> t2 ready
        ready_ids = {t["id"] for t in scheduler.ready_tasks(conn)}
        assert t2 in ready_ids
    finally:
        conn.close()


def test_merge_order_is_topological():
    # edges are (task, dependency): b depends-on a, c depends-on b
    order = scheduler.merge_order(["a", "b", "c"], [("b", "a"), ("c", "b")])
    assert order.index("a") < order.index("b") < order.index("c")


def test_merge_order_detects_cycle():
    with pytest.raises(ValueError):
        scheduler.merge_order(["a", "b"], [("a", "b"), ("b", "a")])

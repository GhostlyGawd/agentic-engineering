import json
import pytest
from agentic_mcp import db, nodes, relations, queries


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def test_query_filter_by_type(conn):
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T1")
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T2")
    nodes.create_node(conn, "Goal", status="active", owner="a", body="G")
    out = queries.query_graph(conn, type="Task")
    assert len(out) == 2
    assert all(r["type"] == "Task" for r in out)


def test_query_filter_by_status(conn):
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T1")
    nodes.create_node(conn, "Task", status="done", owner="a", body="T2")
    out = queries.query_graph(conn, type="Task", status="done")
    assert len(out) == 1
    assert out[0]["body"] == "T2"


def test_query_filter_by_scope(conn):
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T1", scope="repo-a")
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T2", scope="repo-b")
    out = queries.query_graph(conn, type="Task", scope="repo-a")
    assert len(out) == 1
    assert out[0]["body"] == "T1"


def test_get_required_reads(conn):
    g = nodes.create_node(conn, "Goal", status="active", owner="a", body="goal")
    m = nodes.create_node(conn, "Module", status="active", owner="a", body="auth")
    sid = nodes.create_node(
        conn, "Spec", status="draft", owner="a", body="spec",
        criteria_json=json.dumps([{"text": "x", "verify": "y", "satisfied": False}]),
        feedback_loop="manual",
        required_reads=json.dumps([g, m]),
    )
    out = queries.get_required_reads(conn, sid)
    assert len(out) == 2
    types = {r["type"] for r in out}
    assert types == {"Goal", "Module"}


def test_walk_down(conn):
    g = nodes.create_node(conn, "Goal", status="active", owner="a", body="G")
    e = nodes.create_node(conn, "Epic", status="active", owner="a", body="E")
    t = nodes.create_node(conn, "Task", status="pending", owner="a", body="T")
    relations.link_nodes(conn, e, g, "implements")
    relations.link_nodes(conn, t, e, "implements")
    out = queries.walk_down(conn, g, max_depth=3)
    ids = {n["id"] for n in out}
    assert {e, t}.issubset(ids)

import pytest
from agentic_mcp import db, nodes, relations


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def _two_tasks(conn):
    a = nodes.create_node(conn, "Task", status="pending", owner="a", body="A")
    b = nodes.create_node(conn, "Task", status="pending", owner="a", body="B")
    return a, b


def test_link_basic(conn):
    a, b = _two_tasks(conn)
    relations.link_nodes(conn, a, b, "depends-on")
    rows = conn.execute(
        "SELECT relation_type FROM relations WHERE from_id=? AND to_id=?", (a, b)
    ).fetchall()
    assert rows == [("depends-on",)]


def test_link_rejects_unknown_type(conn):
    a, b = _two_tasks(conn)
    with pytest.raises(ValueError):
        relations.link_nodes(conn, a, b, "not-a-relation")


def test_link_is_idempotent(conn):
    a, b = _two_tasks(conn)
    relations.link_nodes(conn, a, b, "depends-on")
    relations.link_nodes(conn, a, b, "depends-on")  # second call must not raise
    rows = conn.execute(
        "SELECT count(*) FROM relations WHERE from_id=? AND to_id=?", (a, b)
    ).fetchone()
    assert rows[0] == 1


def test_neighbors_out(conn):
    a, b = _two_tasks(conn)
    c = nodes.create_node(conn, "Task", status="pending", owner="a", body="C")
    relations.link_nodes(conn, a, b, "depends-on")
    relations.link_nodes(conn, a, c, "depends-on")
    out = sorted(relations.neighbors(conn, a, "depends-on", direction="out"))
    assert out == sorted([b, c])


def test_neighbors_in(conn):
    a, b = _two_tasks(conn)
    relations.link_nodes(conn, a, b, "blocks")
    assert relations.neighbors(conn, b, "blocks", direction="in") == [a]


def test_neighbors_any_type(conn):
    a, b = _two_tasks(conn)
    relations.link_nodes(conn, a, b, "depends-on")
    relations.link_nodes(conn, a, b, "references")
    assert sorted(relations.neighbors(conn, a, direction="out")) == [b, b]

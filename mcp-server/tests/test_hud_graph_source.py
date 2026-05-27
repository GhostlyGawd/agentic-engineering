import sqlite3

import pytest

from agentic_mcp import db, nodes
from agentic_mcp.hud.graph_source import GraphSource


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "graph.db"
    db.init_db(p)
    return p


def test_changed_flips_once_after_external_commit(db_path):
    src = GraphSource(db_path)
    try:
        assert src.changed() is False  # nothing changed since open
        writer = db.connect(db_path)
        nodes.create_node(writer, "Goal", status="open", owner="t", body="new")
        writer.close()
        assert src.changed() is True   # detected the external commit
        assert src.changed() is False  # no further change
    finally:
        src.close()


def test_connection_is_read_only(db_path):
    src = GraphSource(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            src.conn.execute(
                "INSERT INTO goal(id,type,status,owner,body,created_at,last_touched)"
                " VALUES ('x','Goal','open','t','b','2026-05-26','2026-05-26')")
            src.conn.commit()
    finally:
        src.close()


def test_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        GraphSource(tmp_path / "nope.db")

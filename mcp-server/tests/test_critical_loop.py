"""CriticalLoop entity registration + (Task 2) lifecycle."""
import pytest

from agentic_mcp import db, nodes


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def test_create_and_get_critical_loop(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        lid = nodes.create_node(
            conn, "CriticalLoop", status="open", owner="system",
            body="loop for finding X", finding_id="find-123",
            started_at="2026-05-20T00:00:00+00:00",
        )
        row = nodes.get_node(conn, lid)
        assert row is not None
        assert row["type"] == "CriticalLoop"
        assert row["finding_id"] == "find-123"
        assert row["iteration_count"] == 1  # column default
    finally:
        conn.close()


def test_critical_loop_requires_finding_id(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        with pytest.raises(ValueError, match="missing required field"):
            nodes.create_node(
                conn, "CriticalLoop", status="open", owner="system",
                body="loop", started_at="2026-05-20T00:00:00+00:00",
            )
    finally:
        conn.close()

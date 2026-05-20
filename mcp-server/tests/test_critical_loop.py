"""CriticalLoop entity registration + (Task 2) lifecycle."""
import pytest

from agentic_mcp import db, nodes, findings, loops


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


# ---------------------------------------------------------------------------
# Task 2: Lifecycle tests
# ---------------------------------------------------------------------------

def _spec_with_finding(conn):
    import json
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
        feedback_loop="if a user reports a bug we open a PR and write a retro",
    )
    fid = findings.log_finding(conn, spec_id, "Critical", body="boom")
    return spec_id, fid


def test_start_and_get_open_loops(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        _, fid = _spec_with_finding(conn)
        lid = loops.start_critical_loop(conn, fid)
        opens = loops.get_open_loops(conn)
        assert [l["id"] for l in opens] == [lid]
        assert opens[0]["iteration_count"] == 1
    finally:
        conn.close()


def test_advance_fires_diagnostic_at_three(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        _, fid = _spec_with_finding(conn)
        lid = loops.start_critical_loop(conn, fid)
        loops.advance_critical_loop(conn, lid)  # -> 2
        assert nodes.get_node(conn, lid)["diagnostic_fired_at"] is None
        loops.advance_critical_loop(conn, lid)  # -> 3, fires
        stamped = nodes.get_node(conn, lid)["diagnostic_fired_at"]
        assert stamped is not None
        loops.advance_critical_loop(conn, lid)  # -> 4, NOT re-stamped
        assert nodes.get_node(conn, lid)["diagnostic_fired_at"] == stamped
    finally:
        conn.close()


def test_resolve_then_survives_reopen(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    _, fid = _spec_with_finding(conn)
    lid = loops.start_critical_loop(conn, fid)
    loops.resolve_critical_loop(conn, lid)
    conn.close()
    conn2 = db.connect(tmp_db_path)
    try:
        assert loops.get_open_loops(conn2) == []
        assert nodes.get_node(conn2, lid)["status"] == "resolved"
        assert nodes.get_node(conn2, lid)["resolved_at"] is not None
    finally:
        conn2.close()

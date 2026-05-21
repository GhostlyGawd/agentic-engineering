import json
import pytest

from agentic_mcp import db, findings, nodes

_FB = "if a user reports a bug we open a PR and write a retro"


def _spec(conn):
    return nodes.create_node(
        conn, "Spec", status="open", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x.py::t -q"}]),
        feedback_loop=_FB,
    )


def _conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def test_log_finding_stores_criterion_and_iteration(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = _spec(conn)
        fid = findings.log_finding(
            conn, sid, "Critical", body="boom",
            criterion_index=2, loop_iteration=1,
        )
        row = nodes.get_node(conn, fid)
        assert row["criterion_index"] == 2
        assert row["loop_iteration"] == 1
    finally:
        conn.close()


def test_record_triage_sets_decision_on_important(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = _spec(conn)
        fid = findings.log_finding(conn, sid, "Important", body="n+1 query")
        findings.record_triage(conn, fid, "fix-in-pr")
        assert nodes.get_node(conn, fid)["triage"] == "fix-in-pr"
        findings.record_triage(conn, fid, "backlog")
        assert nodes.get_node(conn, fid)["triage"] == "backlog"
    finally:
        conn.close()


def test_record_triage_rejects_bad_decision(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = _spec(conn)
        fid = findings.log_finding(conn, sid, "Important", body="x")
        with pytest.raises(ValueError, match="triage decision"):
            findings.record_triage(conn, fid, "later")
    finally:
        conn.close()


def test_record_triage_rejects_non_important(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = _spec(conn)
        fid = findings.log_finding(conn, sid, "Critical", body="x")
        with pytest.raises(ValueError, match="Important"):
            findings.record_triage(conn, fid, "fix-in-pr")
    finally:
        conn.close()

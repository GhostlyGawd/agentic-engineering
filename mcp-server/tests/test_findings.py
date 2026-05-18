import json
import pytest
from agentic_mcp import db, nodes, findings


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def _scoped_task(conn, scope):
    return nodes.create_node(
        conn, "Task", status="pending", owner="a", body="T", scope=scope
    )


def test_log_finding_inherits_scope(conn):
    pid = _scoped_task(conn, "repo-a/module-x")
    fid = findings.log_finding(conn, pid, "Important", "missing null check")
    f = nodes.get_node(conn, fid)
    assert f["scope"] == "repo-a/module-x"
    assert f["severity"] == "Important"
    assert f["parent_id"] == pid


def test_log_finding_explicit_scope_wins(conn):
    pid = _scoped_task(conn, "repo-a")
    fid = findings.log_finding(conn, pid, "Critical", "x", scope="repo-b")
    assert nodes.get_node(conn, fid)["scope"] == "repo-b"


def test_log_finding_unknown_severity_rejected(conn):
    pid = _scoped_task(conn, "repo-a")
    with pytest.raises(ValueError):
        findings.log_finding(conn, pid, "Catastrophic", "x")


def test_log_finding_missing_parent_rejected(conn):
    with pytest.raises(ValueError):
        findings.log_finding(conn, "no-such-node", "Critical", "x")


def test_mark_criterion_satisfied_happy_path(conn):
    crit = json.dumps([
        {"text": "func returns 42", "verify": "pytest tests/test_x.py", "satisfied": False},
    ])
    sid = nodes.create_node(
        conn, "Spec", status="draft", owner="a", body="s",
        criteria_json=crit, feedback_loop="manual",
    )
    findings.mark_criterion_satisfied(conn, sid, 0, evidence="pytest passed at HEAD")
    out = json.loads(nodes.get_node(conn, sid)["criteria_json"])
    assert out[0]["satisfied"] is True
    assert out[0]["evidence"] == "pytest passed at HEAD"


def test_mark_criterion_empty_evidence_rejected(conn):
    crit = json.dumps([{"text": "x", "verify": "y", "satisfied": False}])
    sid = nodes.create_node(
        conn, "Spec", status="draft", owner="a", body="s",
        criteria_json=crit, feedback_loop="manual",
    )
    with pytest.raises(ValueError, match="evidence"):
        findings.mark_criterion_satisfied(conn, sid, 0, evidence="   ")


def test_mark_criterion_out_of_range(conn):
    crit = json.dumps([{"text": "x", "verify": "y", "satisfied": False}])
    sid = nodes.create_node(
        conn, "Spec", status="draft", owner="a", body="s",
        criteria_json=crit, feedback_loop="manual",
    )
    with pytest.raises(IndexError):
        findings.mark_criterion_satisfied(conn, sid, 5, evidence="x")

import json
import pytest
from agentic_mcp import db, nodes


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def test_create_goal_auto_id_and_timestamps(conn):
    nid = nodes.create_node(conn, "Goal", status="active", owner="alice", body="ship MVP")
    row = nodes.get_node(conn, nid)
    assert row["type"] == "Goal"
    assert row["owner"] == "alice"
    assert row["body"] == "ship MVP"
    assert row["created_at"] is not None
    assert row["last_touched"] == row["created_at"]


def test_create_with_explicit_id(conn):
    nid = nodes.create_node(
        conn, "Task", id="task-001", status="pending", owner="alice", body="do X"
    )
    assert nid == "task-001"


def test_missing_required_raises(conn):
    with pytest.raises(ValueError, match="body"):
        nodes.create_node(conn, "Goal", status="active", owner="alice")


def test_spec_requires_criteria_and_feedback(conn):
    with pytest.raises(ValueError, match="criteria_json"):
        nodes.create_node(
            conn, "Spec", status="draft", owner="alice", body="x",
            feedback_loop="test runs in CI",
        )
    with pytest.raises(ValueError, match="feedback_loop"):
        nodes.create_node(
            conn, "Spec", status="draft", owner="alice", body="x",
            criteria_json=json.dumps([{"text": "x", "verify": "y", "satisfied": False}]),
        )


def test_finding_requires_severity_and_parent(conn):
    with pytest.raises(ValueError):
        nodes.create_node(conn, "Finding", status="open", owner="alice", body="x")


def test_update_bumps_last_touched(conn):
    import time
    nid = nodes.create_node(conn, "Goal", status="active", owner="alice", body="x")
    orig = nodes.get_node(conn, nid)["last_touched"]
    time.sleep(1.1)
    nodes.update_node(conn, nid, body="y")
    after = nodes.get_node(conn, nid)
    assert after["body"] == "y"
    assert after["last_touched"] > orig


def test_round_trip_all_entity_types(conn):
    bodies = {
        "Goal": dict(status="active", owner="a", body="b"),
        "Epic": dict(status="active", owner="a", body="b"),
        "Task": dict(status="pending", owner="a", body="b"),
        "Subtask": dict(status="pending", owner="a", body="b"),
        "Spec": dict(
            status="draft", owner="a", body="b",
            criteria_json=json.dumps([{"text": "x", "verify": "y", "satisfied": False}]),
            feedback_loop="manual user observation",
        ),
        "Decision": dict(status="locked", owner="a", body="b"),
        "Bug": dict(status="open", owner="a", body="b"),
        "Finding": dict(status="open", owner="a", body="b", severity="Critical", parent_id="root"),
        "Pattern": dict(status="observed", owner="a", body="b"),
        "Module": dict(status="active", owner="a", body="b"),
        "File": dict(status="active", owner="a", body="b", path="src/x.py"),
        "Review": dict(status="closed", owner="a", body="b"),
        "Retro": dict(status="open", owner="a", body="b"),
        "ArchDebt": dict(status="open", owner="a", body="b"),
    }
    for ntype, fields in bodies.items():
        nid = nodes.create_node(conn, ntype, **fields)
        out = nodes.get_node(conn, nid)
        assert out is not None, f"round-trip failed for {ntype}"
        assert out["type"] == ntype


def test_get_node_missing_returns_none(conn):
    assert nodes.get_node(conn, "does-not-exist") is None

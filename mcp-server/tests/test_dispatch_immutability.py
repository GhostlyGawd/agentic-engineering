import json
import pytest

from agentic_mcp import db, dispatch, nodes, validators

_CRIT = [
    {"text": "basic", "verify": "pytest test_x.py::test_basic -q"},
    {"text": "edge", "verify": "pytest test_x.py::test_edge -q"},
]
_FB = "if a user reports a bug we open a PR and write a retro"


def _mk_spec(conn):
    return nodes.create_node(
        conn, "Spec", status="open", owner="t", body="spec",
        criteria_json=json.dumps(_CRIT), feedback_loop=_FB,
    )


def test_dispatch_sets_timestamp_once(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        sid = _mk_spec(conn)
        dispatch.dispatch_spec(conn, sid)
        first = nodes.get_node(conn, sid)["dispatched_at"]
        assert first is not None
        dispatch.dispatch_spec(conn, sid)  # no-op
        assert nodes.get_node(conn, sid)["dispatched_at"] == first
    finally:
        conn.close()


def test_dispatched_criteria_are_immutable(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        sid = _mk_spec(conn)
        dispatch.dispatch_spec(conn, sid)
        changed = [dict(_CRIT[0]), {"text": "NEW", "verify": "pytest test_x.py::test_new -q"}]
        ok, reasons = validators.validate_dispatched_immutable(conn, sid, changed)
        assert not ok
        assert any("supersede" in r.lower() for r in reasons)
    finally:
        conn.close()


def test_predispatch_criteria_mutable(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        sid = _mk_spec(conn)  # not dispatched
        changed = [dict(_CRIT[0])]
        ok, reasons = validators.validate_dispatched_immutable(conn, sid, changed)
        assert ok, reasons
    finally:
        conn.close()

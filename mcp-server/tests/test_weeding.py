"""Anti-rot weeding + stale-spec detection."""
import json
from datetime import datetime, timedelta, timezone

from agentic_mcp import db, nodes, weeding


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def _old_iso(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _dispatched_spec(conn, last_touched):
    sid = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
        feedback_loop="if a user reports a bug we open a PR and write a retro",
    )
    conn.execute("UPDATE spec SET last_touched=? WHERE id=?", (last_touched, sid))
    conn.commit()
    return sid


def test_find_stale_nodes_flags_old_excludes_fresh(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        old = _dispatched_spec(conn, _old_iso(30))
        fresh = _dispatched_spec(conn, _old_iso(1))
        stale_ids = {n["id"] for n in weeding.find_stale_nodes(conn, days=14)}
        assert old in stale_ids
        assert fresh not in stale_ids
    finally:
        conn.close()


def test_flag_stale_specs_stamps_and_clears(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        sid = _dispatched_spec(conn, _old_iso(30))
        flagged = weeding.flag_stale_specs(conn, days=14)
        assert sid in flagged
        assert nodes.get_node(conn, sid)["stale_flagged_at"] is not None
        conn.execute("UPDATE spec SET last_touched=? WHERE id=?", (_old_iso(0), sid))
        conn.commit()
        flagged2 = weeding.flag_stale_specs(conn, days=14)
        assert sid not in flagged2
        assert nodes.get_node(conn, sid)["stale_flagged_at"] is None
    finally:
        conn.close()

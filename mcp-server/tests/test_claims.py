"""Claim lifecycle + serial-when-shared overlap detection."""
import pytest

from agentic_mcp import db, claims


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def test_claim_then_release(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        cid = claims.claim_scope(conn, "task-1", ["src/a/*"], worktree="wt1", branch="b1")
        rows = list(conn.execute("SELECT status FROM claim WHERE id=?", (cid,)))
        assert rows[0][0] == "held"
        claims.release_claim(conn, cid)
        rows = list(conn.execute("SELECT status FROM claim WHERE id=?", (cid,)))
        assert rows[0][0] == "released"
    finally:
        conn.close()


def test_overlapping_claim_conflicts(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        claims.claim_scope(conn, "task-1", ["src/a/*"])
        with pytest.raises(claims.ClaimConflict):
            claims.claim_scope(conn, "task-2", ["src/a/b.py"])
    finally:
        conn.close()


def test_released_claim_does_not_conflict(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        cid = claims.claim_scope(conn, "task-1", ["src/a/*"])
        claims.release_claim(conn, cid)
        claims.claim_scope(conn, "task-2", ["src/a/b.py"])  # no raise
    finally:
        conn.close()


def test_detect_overlap_returns_max_disjoint_batch(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        candidates = [
            {"task_id": "t1", "scope_paths": ["src/a/*"]},
            {"task_id": "t2", "scope_paths": ["src/a/x.py"]},  # overlaps t1 -> dropped
            {"task_id": "t3", "scope_paths": ["src/b/*"]},
            {"task_id": "t4", "scope_paths": ["src/c/*"]},
        ]
        batch = claims.detect_overlap(candidates)
        assert [c["task_id"] for c in batch] == ["t1", "t3", "t4"]
    finally:
        conn.close()

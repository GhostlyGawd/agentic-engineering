"""Per-role trust-weighting calibration."""
from agentic_mcp import db, calibration


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def test_unknown_role_has_neutral_default(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        c = calibration.get_calibration(conn, "code-reviewer")
        assert c["score"] == 0.5
        assert c["distrusted"] == 0
        assert c["observations"] == 0
    finally:
        conn.close()


def test_record_outcome_updates_score(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(5):
            calibration.record_outcome(conn, "code-reviewer", hit=True)
        c = calibration.get_calibration(conn, "code-reviewer")
        assert c["observations"] == 5
        assert c["hits"] == 5
        assert c["misses"] == 0
        assert c["score"] > 0.7  # 6/7 with Laplace smoothing
    finally:
        conn.close()


def test_adjust_trust_fires_on_low_score(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(8):
            calibration.record_outcome(conn, "contrarian", hit=False)
        res = calibration.adjust_trust(conn, "contrarian")
        assert res["adjusted"] is True
        assert res["distrusted"] == 1
        assert calibration.get_calibration(conn, "contrarian")["last_adjusted_at"] is not None
        res2 = calibration.adjust_trust(conn, "contrarian")
        assert res2["adjusted"] is False
    finally:
        conn.close()


def test_adjust_trust_clears_on_recovery(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(8):
            calibration.record_outcome(conn, "contrarian", hit=False)
        calibration.adjust_trust(conn, "contrarian")  # distrust set
        for _ in range(40):
            calibration.record_outcome(conn, "contrarian", hit=True)
        res = calibration.adjust_trust(conn, "contrarian")  # score now high
        assert res["adjusted"] is True
        assert res["distrusted"] == 0
    finally:
        conn.close()

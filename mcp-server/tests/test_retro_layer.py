import json
import sqlite3
import pytest

from agentic_mcp import db, findings, nodes, relations

_FB = "if a user reports a bug we open a PR and write a retro"


def _conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


@pytest.mark.parametrize("layer", ["spec", "implementation", "review", "unknowable"])
def test_log_retro_accepts_valid_layers(tmp_db_path, layer):
    conn = _conn(tmp_db_path)
    try:
        rid = findings.log_retro(conn, body=f"retro for {layer}", failed_layer=layer)
        assert nodes.get_node(conn, rid)["failed_layer"] == layer
    finally:
        conn.close()


def test_log_retro_rejects_unknown_layer(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        with pytest.raises(ValueError, match="failed_layer"):
            findings.log_retro(conn, body="x", failed_layer="process")
    finally:
        conn.close()


def test_db_check_rejects_unknown_layer(tmp_db_path):
    # Bypassing the wrapper, the column CHECK must still reject out-of-set values.
    conn = _conn(tmp_db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK|failed_layer"):
            conn.execute(
                "INSERT INTO retro(id,type,status,owner,created_at,last_touched,body,failed_layer)"
                " VALUES ('r1','Retro','open','t','2026-05-20T00:00:00+00:00',"
                "'2026-05-20T00:00:00+00:00','b','process')"
            )
            conn.commit()
    finally:
        conn.close()


def test_log_retro_links_caused_by(tmp_db_path):
    conn = _conn(tmp_db_path)
    try:
        sid = nodes.create_node(
            conn, "Spec", status="open", owner="t", body="s",
            criteria_json=json.dumps([{"text": "c", "verify": "pytest x.py::t -q"}]),
            feedback_loop=_FB,
        )
        fid = findings.log_finding(conn, sid, "Critical", body="boom")
        rid = findings.log_retro(
            conn, body="root cause was impl", failed_layer="implementation",
            caused_by_finding_id=fid,
        )
        assert fid in relations.neighbors(conn, rid, "caused-by", direction="out")
    finally:
        conn.close()

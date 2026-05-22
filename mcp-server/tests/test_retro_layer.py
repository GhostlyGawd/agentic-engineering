import json
import sqlite3
import pytest

from agentic_mcp import db, findings, nodes, relations

_FB = "if a user reports a bug we open a PR and write a retro"


def _conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


@pytest.mark.parametrize(
    "layer", ["spec", "implementation", "integration", "review", "unknowable"]
)
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


def test_db_check_accepts_integration_layer(tmp_db_path):
    # The integration layer (config/packaging/wiring failures) must be a
    # first-class failed_layer value, accepted by both the wrapper and the
    # column CHECK on a freshly initialised DB.
    conn = _conn(tmp_db_path)
    try:
        rid = findings.log_retro(
            conn, body="MCP never connected: wiring defect", failed_layer="integration"
        )
        assert nodes.get_node(conn, rid)["failed_layer"] == "integration"
    finally:
        conn.close()


def test_migration_upgrades_old_retro_check_to_accept_integration(tmp_db_path):
    # A DB created before the integration layer existed has the OLD CHECK
    # baked into its retro table. SQLite cannot ALTER a CHECK constraint, so
    # apply_migrations() must rebuild the table. Simulate the old DB by hand,
    # then confirm reopening it (which runs migrations) accepts 'integration'.
    # Build a complete current DB, then surgically downgrade only the retro
    # table back to the old CHECK and reset user_version. This reproduces the
    # exact state of a real pre-integration DB (all tables present, retro
    # narrowly constrained) without depending on a snapshot of the old schema.
    db.init_db(tmp_db_path)
    raw = sqlite3.connect(str(tmp_db_path))
    try:
        raw.executescript(
            "DROP TABLE retro;"
            "CREATE TABLE retro ("
            " id TEXT PRIMARY KEY,"
            " type TEXT NOT NULL CHECK(type='Retro'),"
            " status TEXT NOT NULL, severity TEXT, owner TEXT,"
            " created_at TEXT NOT NULL, last_touched TEXT NOT NULL,"
            " body TEXT NOT NULL, summary TEXT, tags TEXT, scope TEXT,"
            " failed_layer TEXT CHECK(failed_layer IN"
            " ('spec','implementation','review','unknowable')));"
        )
        # A pre-existing row must survive the rebuild.
        raw.execute(
            "INSERT INTO retro(id,type,status,owner,created_at,last_touched,body,failed_layer)"
            " VALUES ('old1','Retro','open','t','2026-05-20T00:00:00+00:00',"
            "'2026-05-20T00:00:00+00:00','legacy retro','implementation')"
        )
        raw.execute("PRAGMA user_version = 1")  # Phase 1-era DB
        raw.commit()
    finally:
        raw.close()

    # connect() runs apply_migrations(); the rebuilt CHECK must now allow it.
    conn = db.connect(tmp_db_path)
    try:
        rid = findings.log_retro(
            conn, body="now expressible", failed_layer="integration"
        )
        assert nodes.get_node(conn, rid)["failed_layer"] == "integration"
        assert nodes.get_node(conn, "old1")["body"] == "legacy retro"
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

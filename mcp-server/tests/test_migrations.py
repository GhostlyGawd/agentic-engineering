# mcp-server/tests/test_migrations.py
"""Phase 1 migration: idempotent, additive, applies to fresh + Phase 0 DBs."""
from agentic_mcp import db, migrations


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_db_gets_phase1_schema(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        assert "dispatched_at" in _columns(conn, "spec")
        assert {"criterion_index", "loop_iteration", "triage"} <= _columns(conn, "finding")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "critical_loop" in tables
        assert conn.execute("PRAGMA user_version").fetchone()[0] == migrations.SCHEMA_VERSION
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        before = _columns(conn, "finding")
        migrations.apply_migrations(conn)  # second explicit run
        after = _columns(conn, "finding")
        assert before == after
        assert conn.execute("PRAGMA user_version").fetchone()[0] == migrations.SCHEMA_VERSION
    finally:
        conn.close()


def test_upgrades_phase0_db(tmp_db_path):
    # Simulate a Phase 0 DB: run only schema.sql, leave user_version at 0.
    import sqlite3
    from pathlib import Path
    schema = (Path(db.__file__).with_name("schema.sql")).read_text(encoding="utf-8")
    raw = sqlite3.connect(str(tmp_db_path))
    raw.executescript(schema)
    raw.commit()
    raw.close()
    # Now open via db.connect, which must migrate it.
    conn = db.connect(tmp_db_path)
    try:
        assert "dispatched_at" in _columns(conn, "spec")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == migrations.SCHEMA_VERSION
    finally:
        conn.close()


def test_fresh_db_is_v3_with_phase2_tables(tmp_db_path):
    from agentic_mcp import db
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"claim", "calibration"} <= names
        spec_cols = {r[1] for r in conn.execute("PRAGMA table_info(spec)")}
        assert "stale_flagged_at" in spec_cols
    finally:
        conn.close()


def test_v2_db_upgrades_to_v3(tmp_db_path):
    import sqlite3
    from agentic_mcp import db, migrations
    db.init_db(tmp_db_path)
    raw = sqlite3.connect(str(tmp_db_path))
    raw.executescript("DROP TABLE IF EXISTS claim; DROP TABLE IF EXISTS calibration;")
    raw.execute("PRAGMA user_version = 2")
    raw.commit()
    raw.close()

    conn = db.connect(tmp_db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"claim", "calibration"} <= names
        migrations.apply_migrations(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()

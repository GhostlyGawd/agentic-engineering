import sqlite3
from agentic_mcp import db, nodes


def test_init_db_creates_file(tmp_db_path):
    db.init_db(tmp_db_path)
    assert tmp_db_path.exists()


def test_all_entity_tables_present(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r[0] for r in rows}
    expected = {
        "goal", "epic", "task", "subtask", "spec", "decision",
        "bug", "finding", "pattern", "module", "file",
        "review", "retro", "arch_debt", "relations",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_relations_check_constraint(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    # Should reject unknown relation type
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO relations(from_id, to_id, relation_type, created_at) VALUES (?,?,?,?)",
            ("a", "b", "not-a-real-relation", "2026-05-17T00:00:00+00:00"),
        )
        conn.commit()


def test_init_is_idempotent(tmp_db_path):
    db.init_db(tmp_db_path)
    db.init_db(tmp_db_path)  # second call must not raise
    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()
    assert rows[0] >= 15  # 14 entity tables + relations


def test_resolve_db_path_uses_env_override(tmp_path, monkeypatch):
    """resolve_db_path honors AGENTIC_DB_PATH env var."""
    target = tmp_path / "custom" / "graph.db"
    monkeypatch.setenv("AGENTIC_DB_PATH", str(target))
    p = db.resolve_db_path()
    assert p == target.resolve()
    assert p.exists()  # init_db created it (parents included)


def test_resolve_db_path_default_when_unset(tmp_path, monkeypatch):
    """resolve_db_path defaults to ./.agentic/graph.db when env var unset."""
    monkeypatch.delenv("AGENTIC_DB_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    p = db.resolve_db_path()
    assert p == (tmp_path / ".agentic" / "graph.db").resolve()
    assert p.exists()


def test_connect_sets_busy_timeout(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        # PRAGMA busy_timeout returns the current value in milliseconds.
        (value,) = conn.execute("PRAGMA busy_timeout").fetchone()
        assert value == 5000
    finally:
        conn.close()


def test_resolve_db_path_existing_not_reinitialized(tmp_path, monkeypatch):
    """resolve_db_path does not destructively re-init existing DB."""
    target = tmp_path / "graph.db"
    db.init_db(target)
    conn = db.connect(target)
    nid = nodes.create_node(conn, "Goal", status="open", owner="t", body="b")
    conn.close()
    monkeypatch.setenv("AGENTIC_DB_PATH", str(target))
    p = db.resolve_db_path()  # exists -> must not touch it
    conn2 = db.connect(p)
    assert nodes.get_node(conn2, nid) is not None  # data survived
    conn2.close()

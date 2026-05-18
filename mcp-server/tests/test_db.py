import sqlite3
from agentic_mcp import db


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

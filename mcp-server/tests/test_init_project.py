import json
import sqlite3
import pytest
from agentic_mcp import init_project, db


def test_init_creates_layout(tmp_path):
    init_project.run(project_root=tmp_path, scope_mode="isolated")
    assert (tmp_path / ".agentic" / "graph.db").exists()
    cfg = json.loads((tmp_path / ".agentic" / "config.json").read_text())
    assert cfg["scope_mode"] == "isolated"
    assert (tmp_path / ".agentic" / "compatibility.json").exists()
    assert (tmp_path / ".agentic" / "specs").is_dir()


def test_init_invalid_scope_mode(tmp_path):
    with pytest.raises(ValueError):
        init_project.run(project_root=tmp_path, scope_mode="multiverse")


def test_init_is_nondestructive(tmp_path):
    init_project.run(project_root=tmp_path, scope_mode="isolated")
    # Insert a marker row to confirm second init does not wipe.
    conn = db.connect(tmp_path / ".agentic" / "graph.db")
    conn.execute(
        "INSERT INTO goal(id,type,status,owner,body,created_at,last_touched) "
        "VALUES ('g-marker','Goal','active','test','marker','2026-01-01','2026-01-01')"
    )
    conn.commit()
    conn.close()

    init_project.run(project_root=tmp_path, scope_mode="workspace")
    # Marker still present:
    conn = sqlite3.connect(tmp_path / ".agentic" / "graph.db")
    rows = conn.execute("SELECT body FROM goal WHERE id='g-marker'").fetchall()
    assert rows == [("marker",)]
    # Config updated:
    cfg = json.loads((tmp_path / ".agentic" / "config.json").read_text())
    assert cfg["scope_mode"] == "workspace"

import subprocess
from pathlib import Path

from agentic_mcp import db, stability


def _git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )


def _init_repo(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    return repo


def test_contradiction_logged_on_identical_blob_with_prior_approval(tmp_path, tmp_db_path):
    repo = _init_repo(tmp_path / "r")
    (repo / "x.py").write_text("def f():\n    return 1\n")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "c1")
    c1 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # Change an UNRELATED file so x.py's blob is identical across c1..c2.
    (repo / "y.py").write_text("y = 1\n")
    _git(repo, "add", "y.py")
    _git(repo, "commit", "-q", "-m", "c2")
    c2 = _git(repo, "rev-parse", "HEAD").stdout.strip()

    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        pid = stability.detect_stability_contradiction(
            conn, str(repo), "x.py", c1, c2, prior_approval=True
        )
        assert pid is not None
        assert db.connect  # sanity
        row = conn.execute("SELECT type, tags FROM pattern WHERE id=?", (pid,)).fetchone()
        assert row[0] == "Pattern"
        assert "stability" in (row[1] or "")
    finally:
        conn.close()


def test_no_contradiction_without_prior_approval(tmp_path, tmp_db_path):
    repo = _init_repo(tmp_path / "r")
    (repo / "x.py").write_text("def f():\n    return 1\n")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "c1")
    c1 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "y.py").write_text("y = 1\n")
    _git(repo, "add", "y.py")
    _git(repo, "commit", "-q", "-m", "c2")
    c2 = _git(repo, "rev-parse", "HEAD").stdout.strip()

    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        pid = stability.detect_stability_contradiction(
            conn, str(repo), "x.py", c1, c2, prior_approval=False
        )
        assert pid is None
        assert conn.execute("SELECT COUNT(*) FROM pattern").fetchone()[0] == 0
    finally:
        conn.close()


def test_no_contradiction_when_blob_changed(tmp_path, tmp_db_path):
    repo = _init_repo(tmp_path / "r")
    (repo / "x.py").write_text("def f():\n    return 1\n")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "c1")
    c1 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "x.py").write_text("def f():\n    return 2\n")  # blob CHANGES
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "c2")
    c2 = _git(repo, "rev-parse", "HEAD").stdout.strip()

    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        pid = stability.detect_stability_contradiction(
            conn, str(repo), "x.py", c1, c2, prior_approval=True
        )
        assert pid is None
    finally:
        conn.close()

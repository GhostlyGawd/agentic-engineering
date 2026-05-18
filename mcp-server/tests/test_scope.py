from pathlib import Path
import pytest
from agentic_mcp import scope


def test_explicit_wins():
    s = scope.infer_scope(
        "anything",
        explicit="repo-a/module-x",
        parent_scope="repo-b",
        cwd=Path("/tmp/whatever"),
        recent_files=["repo-z/foo.py"],
    )
    assert s == "repo-a/module-x"


def test_parent_scope_used_when_no_explicit():
    s = scope.infer_scope(
        "anything",
        parent_scope="repo-b/module-y",
        cwd=Path("/tmp/whatever"),
    )
    assert s == "repo-b/module-y"


def test_body_path_mention_used_when_no_parent():
    s = scope.infer_scope(
        "Modified src/auth/login.py and src/auth/session.py to fix a bug",
    )
    assert s == "src/auth"


def test_recent_files_lcp():
    s = scope.infer_scope(
        "no path here",
        recent_files=["src/auth/login.py", "src/auth/session.py", "src/auth/util.py"],
    )
    assert s == "src/auth"


def test_cwd_basename_fallback(tmp_path):
    work = tmp_path / "my-project"
    work.mkdir()
    s = scope.infer_scope("nothing useful", cwd=work)
    assert s == "my-project"


def test_global_when_nothing():
    s = scope.infer_scope("nothing useful")
    assert s == "global"

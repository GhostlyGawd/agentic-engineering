import sys
from pathlib import Path

from agentic_mcp import tick_spawn


def _fake_runner_factory(record):
    def runner(argv, cwd, env):
        record["argv"] = argv
        record["cwd"] = cwd
        record["env"] = env
        class R:
            returncode = 0
            stdout = '{"ok": true}'
            stderr = ""
        return R()
    return runner


def test_spawn_tick_builds_argv_and_env(tmp_path):
    rec = {}
    proj = str(tmp_path / "proj")
    out = tick_spawn.spawn_tick(proj, "orchestrate",
                                runner=_fake_runner_factory(rec))
    assert out["ok"] is True
    assert rec["argv"][0] == sys.executable
    assert "agentic_mcp.orchestrate" in rec["argv"]
    assert "--once" in rec["argv"]
    assert rec["cwd"] == proj
    expected_db = str(Path(proj) / ".agentic" / "graph.db")
    assert rec["env"]["AGENTIC_DB_PATH"] == expected_db


def test_spawn_tick_pattern_finder_maps_to_patterns(tmp_path):
    rec = {}
    tick_spawn.spawn_tick(str(tmp_path), "pattern_finder",
                          runner=_fake_runner_factory(rec))
    assert "agentic_mcp.patterns" in rec["argv"]


def test_spawn_tick_unknown_tick():
    out = tick_spawn.spawn_tick("C:/p", "nope", runner=None)
    assert out["ok"] is False
    assert "unknown tick" in out["error"]


def test_spawn_tick_runner_raises_is_caught(tmp_path):
    def boom(argv, cwd, env):
        raise RuntimeError("spawn failed")
    out = tick_spawn.spawn_tick(str(tmp_path), "orchestrate", runner=boom)
    assert out["ok"] is False
    assert "spawn failed" in out["error"]


def test_spawn_tick_nonzero_returncode(tmp_path):
    def runner(argv, cwd, env):
        class R:
            returncode = 1
            stdout = ""
            stderr = "traceback"
        return R()
    out = tick_spawn.spawn_tick(str(tmp_path), "orchestrate", runner=runner)
    assert out["ok"] is False
    assert "exit 1" in out["error"]

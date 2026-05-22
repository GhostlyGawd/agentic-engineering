# mcp-server/tests/test_llm_harness.py
import json
import sys
from pathlib import Path

import pytest

from llm_harness import _kill_tree, claude_on_path, result_text, run_claude_headless, stage_mcp_config


def test_kill_tree_tolerates_dead_pid():
    _kill_tree(999999)  # nonexistent pid -> must not raise


def test_stage_mcp_config_writes_resolved_server(tmp_path):
    db = tmp_path / ".agentic" / "graph.db"
    p = stage_mcp_config(tmp_path, db)
    cfg = json.loads(Path(p).read_text(encoding="utf-8"))
    srv = cfg["mcpServers"]["agentic-graph"]
    assert srv["command"] == sys.executable
    assert srv["args"] == ["-m", "agentic_mcp.server"]
    assert srv["env"]["AGENTIC_DB_PATH"] == str(db)


@pytest.mark.llm
def test_claude_headless_roundtrips(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    payload = run_claude_headless("Reply with exactly the word: pong", cwd=tmp_path)
    assert "pong" in result_text(payload).lower()

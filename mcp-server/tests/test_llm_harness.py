# mcp-server/tests/test_llm_harness.py
import pytest

from llm_harness import claude_on_path, result_text, run_claude_headless


@pytest.mark.llm
def test_claude_headless_roundtrips(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    payload = run_claude_headless("Reply with exactly the word: pong", cwd=tmp_path)
    assert "pong" in result_text(payload).lower()

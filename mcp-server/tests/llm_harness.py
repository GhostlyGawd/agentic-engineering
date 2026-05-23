# mcp-server/tests/llm_harness.py
"""Back-compat shim. The harness now lives in the package at
agentic_mcp.headless (Phase 2 promoted it out of tests/ so the orchestrator can
import it at runtime). Existing e2e tests import from here unchanged.
"""
from agentic_mcp.headless import (  # noqa: F401
    ClaudeUnavailable,
    _claude_exe,
    _kill_tree,
    claude_on_path,
    result_text,
    run_claude_headless,
    stage_mcp_config,
)

# mcp-server/tests/llm_harness.py
"""Subprocess wrapper around the headless `claude` CLI for real-agent gate tests.

Same subprocess pattern Phase 0 used for PowerShell (test_walkup.py), pointed at
`claude` instead. Runs on the Max subscription - no API key, no metered cost
(design section 11). JSON parsing is isolated here so the e2e asserts on
structured fields, never on raw stdout.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys


class ClaudeUnavailable(RuntimeError):
    pass


def claude_on_path() -> bool:
    return shutil.which("claude") is not None


def _claude_exe() -> str:
    # Resolve the FULL path (with extension) rather than passing a bare "claude".
    # On Windows the CLI is an npm shim (claude.cmd / claude.ps1); subprocess with
    # shell=False uses CreateProcess, which only auto-appends .exe and never searches
    # PATHEXT, so a bare "claude" raises FileNotFoundError. shutil.which honors PATHEXT
    # and returns claude.CMD; on POSIX it returns the bare binary path. No-op there.
    exe = shutil.which("claude")
    if exe is None:
        raise ClaudeUnavailable("`claude` CLI not on PATH")
    return exe


def stage_mcp_config(project, db_path):
    """Write a resolved .mcp.json into *project* registering the agentic-graph server.

    Uses sys.executable so the same venv that runs the tests also runs the MCP
    server subprocess - no PATH ambiguity. Returns the Path to the written file.
    """
    from pathlib import Path
    cfg = {"mcpServers": {"agentic-graph": {
        "command": sys.executable,
        "args": ["-m", "agentic_mcp.server"],
        "env": {"AGENTIC_DB_PATH": str(db_path)},
    }}}
    p = Path(project) / ".mcp.json"
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return p


def run_claude_headless(prompt: str, cwd, timeout: int = 900, mcp_config=None) -> dict:
    exe = _claude_exe()
    # bypassPermissions required: builder agent must write files and call MCP tools
    # during the exit-gate run; without it claude prompts interactively and hangs.
    cmd = [exe, "-p", prompt, "--output-format", "json",
           "--permission-mode", "bypassPermissions"]
    if mcp_config is not None:
        cmd += ["--mcp-config", str(mcp_config), "--strict-mcp-config"]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {proc.returncode}\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        )
    return json.loads(proc.stdout)


def result_text(payload: dict) -> str:
    """Assistant's final text from a `claude -p --output-format json` payload.

    Step-1 spike confirmed the carrying key on this CLI version. If the spike
    showed a different key, change the first branch here to match.
    """
    if isinstance(payload.get("result"), str):
        return payload["result"]
    if isinstance(payload.get("text"), str):  # fallback for CLI drift
        return payload["text"]
    raise KeyError(f"no result/text field in claude payload: {sorted(payload)}")

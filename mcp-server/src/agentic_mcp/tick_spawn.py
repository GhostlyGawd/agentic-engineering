"""Spawn an existing stateless tick CLI as a short-lived subprocess.

The supervisor adds NOTHING to tick logic -- it shells out to the same module
CLIs a human would run (`python -m agentic_mcp.orchestrate --once`). The tick
operates on the project's own graph.db via the AGENTIC_DB_PATH env var. Only
EXISTING CLIs are mapped here; arch_review/promotion are added in later rungs
when their CLIs exist. Never raises: a spawn failure is an outcome dict, so a
crashing tick can never take the daemon down.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# tick name -> module CLI args (after `python -m`). Only ticks with a real
# `--once` CLI today. {repo} is filled with the project path at spawn time.
TICK_COMMANDS: dict[str, list[str]] = {
    "orchestrate": ["agentic_mcp.orchestrate", "--once", "--repo", "{repo}"],
    "pattern_finder": ["agentic_mcp.patterns", "--once", "--repo", "{repo}"],
}

_DEFAULT_TIMEOUT = 1800  # seconds; a hung tick is killed, not waited on forever


def _default_runner(argv, cwd, env):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=_DEFAULT_TIMEOUT)


def spawn_tick(project_path: str, tick: str, *, runner=None) -> dict:
    """Run one tick against project_path's graph.db. Returns an outcome dict;
    never raises. `runner(argv, cwd, env) -> CompletedProcess-like` is injectable
    so tests need no real subprocess."""
    if tick not in TICK_COMMANDS:
        return {"ok": False, "tick": tick, "error": f"unknown tick: {tick!r}"}
    runner = runner or _default_runner
    repo = str(project_path)
    argv = [sys.executable, "-m"] + [
        a.replace("{repo}", repo) for a in TICK_COMMANDS[tick]
    ]
    env = dict(os.environ)
    env["AGENTIC_DB_PATH"] = str(Path(repo) / ".agentic" / "graph.db")
    try:
        proc = runner(argv, repo, env)
    except Exception as e:  # noqa: BLE001 - spawn failure must never propagate
        return {"ok": False, "tick": tick, "error": str(e)}
    if getattr(proc, "returncode", 0) != 0:
        return {"ok": False, "tick": tick,
                "error": f"exit {proc.returncode}: {getattr(proc, 'stderr', '')[:500]}"}
    return {"ok": True, "tick": tick, "stdout": getattr(proc, "stdout", "")}

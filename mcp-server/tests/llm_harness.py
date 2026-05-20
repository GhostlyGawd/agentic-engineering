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


class ClaudeUnavailable(RuntimeError):
    pass


def claude_on_path() -> bool:
    return shutil.which("claude") is not None


def run_claude_headless(prompt: str, cwd, timeout: int = 900) -> dict:
    if not claude_on_path():
        raise ClaudeUnavailable("`claude` CLI not on PATH")
    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json"],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
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

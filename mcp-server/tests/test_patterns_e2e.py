"""Live e2e for the pattern-finder (Task 7 of the pattern-finder plan).

llm-marked: excluded from the fast suite by `addopts = -m "not llm"`. Run on
demand against a live `claude` CLI:
    ./.venv/Scripts/python.exe -m pytest tests/test_patterns_e2e.py -m llm -v

Proves the closed loop with the REAL confirm seam: 3 findings sharing a parent
form one candidate group; the staged pattern-finder agent mints one open Pattern
linked derived-from all 3; then triage moves it to confirmed. One real `claude -p`
session -> slow and subscription-metered; never runs in the fast suite.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_mcp import db, headless, nodes, patterns, relations

pytestmark = pytest.mark.llm

# Repo root that ships agents/pattern-finder.md (tests/ -> mcp-server/ -> repo).
SOURCE_ROOT = str(Path(__file__).resolve().parents[2])


@pytest.mark.skipif(
    not headless.claude_on_path(),
    reason="live claude CLI not on PATH",
)
def test_three_findings_confirmed_pattern(tmp_path):
    # --- 1. Throwaway repo dir (claude cwd + .mcp.json target) --------------
    repo = tmp_path / "repo"
    repo.mkdir()

    # --- 2. Graph DB (the staged mcp_config points the agent at THIS file) --
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)

    # --- 3. A Spec + three findings that share it as parent -----------------
    spec = nodes.create_node(
        conn, "Spec", status="dispatched", owner="e2e", body="auth spec",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
        feedback_loop="open a retro on failure",
    )
    evidence = [
        nodes.create_node(
            conn, "Finding", status="open", owner="e2e", severity="Suggested",
            parent_id=spec,
            body=f"async error path {i} was left unhandled in the auth module")
        for i in range(3)
    ]

    # --- 4. Run the real tick (real _real_confirm; only db_path/repo/src) ----
    result = patterns.find_patterns_tick(
        conn, db_path=db_path, repo=str(repo), source_root=SOURCE_ROOT)

    # --- 5. Structured assertions (no prose inspection) ---------------------
    assert result["considered"] == 1, result
    assert len(result["minted"]) == 1, (
        f"expected one minted Pattern; result={result}")
    pid = result["minted"][0]
    node = nodes.get_node(conn, pid)
    assert node["type"] == "Pattern"
    assert node["status"] == "open"
    linked = set(relations.neighbors(conn, pid, "derived-from", "out"))
    assert set(evidence) <= linked, (
        f"Pattern must link derived-from all evidence; linked={linked}")

    # --- 6. Triage to confirmed --------------------------------------------
    patterns.triage_pattern(conn, pid, "confirmed")
    assert nodes.get_node(conn, pid)["status"] == "confirmed"
    conn.close()

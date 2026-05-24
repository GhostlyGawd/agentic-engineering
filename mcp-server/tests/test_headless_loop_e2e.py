# mcp-server/tests/test_headless_loop_e2e.py
"""Live e2e for the headless build+review loop (Task 6 of the headless loop plan).

llm-marked: excluded from the fast suite by `addopts = -m "not llm"`. Run on
demand against a live `claude` CLI:
    ./.venv/Scripts/python.exe -m pytest tests/test_headless_loop_e2e.py -m llm -v

Proves the closed loop end to end with the REAL seams: a dispatched Spec + Task,
real builder build (graph-assembled prompt), real /agentic:review-pr gate to
CLEAN, then merge. Two real `claude -p` sessions -> slow and subscription-metered;
never runs in the fast suite.

Known nondeterminism (this is a live model-driven test; a red run is more often
environmental than a logic regression):
- The builder may name the file differently or add extra content despite the
  explicit "named hello.txt containing OK" instruction.
- review-pr runs under an 1800s timeout (_real_review); a slow-but-healthy review
  that exceeds it surfaces as NEEDS_FIXING and burns a retry-cap strike.
- The criterion-satisfied assertion depends on `python` resolving on PATH inside
  the worktree when review-pr's spec-checker runs the verify command.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agentic_mcp import db, headless, nodes, orchestrate, relations

pytestmark = pytest.mark.llm


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True, encoding="utf-8")


def _setup_git_repo(repo: Path) -> None:
    _git(["init", "-b", "main"], cwd=str(repo))
    _git(["config", "user.name", "Test Runner"], cwd=str(repo))
    _git(["config", "user.email", "test@example.com"], cwd=str(repo))
    (repo / "README.txt").write_text("headless loop e2e base", encoding="utf-8")
    _git(["add", "README.txt"], cwd=str(repo))
    _git(["commit", "-m", "init: base commit for e2e"], cwd=str(repo))


@pytest.mark.skipif(
    not headless.claude_on_path(),
    reason="live claude CLI not on PATH",
)
def test_build_review_merge_closed_loop(tmp_path):
    # --- 1. Real git repo --------------------------------------------------
    repo = tmp_path / "repo"
    repo.mkdir()
    _setup_git_repo(repo)

    # --- 2. Graph DB (the staged mcp_config points workers at THIS file) ----
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)

    # --- 3. Dispatched Spec + one Task implementing it ----------------------
    # The verify command is a cross-platform Python one-liner: exit 0 iff the
    # file exists. review-pr's spec-checker runs it verbatim in the worktree.
    # NOTE: relies on `python` resolving on PATH in the worktree when the
    # spec-checker runs this; if the criterion-satisfied assert fails live,
    # suspect python resolution before the loop logic.
    verify = "python -c \"import os,sys; sys.exit(0 if os.path.exists('hello.txt') else 1)\""
    spec = nodes.create_node(
        conn, "Spec", status="dispatched", owner="e2e",
        body="Ship hello.txt containing the word OK.",
        criteria_json=json.dumps([{"text": "hello.txt exists", "verify": verify}]),
        feedback_loop="open a retro on failure",
    )
    task = nodes.create_node(
        conn, "Task", status="pending", owner="e2e",
        body="Create a file named hello.txt in the worktree root containing the word OK.",
        tags=json.dumps(["hello.txt"]),
    )
    relations.link_nodes(conn, task, spec, "implements")

    # --- 4. Run the real tick (all real seams; only db_path injected) -------
    # The worktree is the synthetic temp repo, but the review agents + review-pr
    # body come from the REAL repo via source_root (headless has no slash commands;
    # the agents are staged into the worktree's .claude/agents/).
    repo_root = Path(__file__).resolve().parents[2]  # <repo>/mcp-server/tests/.. -> repo root (ships commands/ + agents/)
    try:
        result = orchestrate.tick(
            conn, repo=str(repo), pool_size=1, db_path=db_path,
            source_root=str(repo_root),
        )
    finally:
        # Best-effort: prune only sweeps git's admin entries for worktrees whose
        # dirs are already gone. tick() does no post-merge worktree teardown, so
        # the merged task's worktree dir persists here; pytest's tmp_path cleanup
        # reclaims it.
        try:
            subprocess.run(["git", "worktree", "prune"],
                           cwd=str(repo), capture_output=True)
        except Exception:
            pass
        conn.close()

    # --- 5. Structured assertions (no prose inspection) ---------------------
    assert task in result["dispatched"], (
        f"task should dispatch; dispatched={result['dispatched']}, "
        f"failed={result['failed']}, escalations={result['escalations']}")
    assert task in result["merged"], (
        f"task should merge CLEAN; merged={result['merged']}, "
        f"escalations={result['escalations']}, failed={result['failed']}")
    assert not result["failed"], f"no failure expected; failed={result['failed']}"
    assert (repo / "hello.txt").exists(), "hello.txt missing after merge"

    conn2 = db.connect(db_path)
    try:
        node = nodes.get_node(conn2, task)
        assert node["status"] == "merged", f"task status={node['status']}"
        claim_rows = conn2.execute(
            "SELECT status FROM claim WHERE task_id=?", (task,)).fetchall()
        assert "released" in [r[0] for r in claim_rows], "claim not released"
        # review-pr's spec-checker marked the criterion satisfied.
        spec_node = nodes.get_node(conn2, spec)
        criteria = json.loads(spec_node["criteria_json"])
        assert criteria[0].get("satisfied") is True, (
            f"criterion not marked satisfied: {criteria[0]}")
    finally:
        conn2.close()

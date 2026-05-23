# mcp-server/tests/test_phase2_e2e.py
"""Phase 2 exit-gate: calibration, weeding, and parallel-build e2e.

llm-marked: excluded from the fast suite by the `addopts = -m "not llm"` in
pyproject.toml. Run on demand with -m llm against a live claude CLI.

Three scenarios:

A. Calibration adjustment fires (deterministic - no claude needed).
B. Weeding surfaces a stale spec (deterministic - no claude needed).
C. Two orthogonal specs build in parallel, merge without collision (LIVE).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentic_mcp import calibration, db, headless, nodes, orchestrate, relations, weeding

pytestmark = pytest.mark.llm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_conn(tmp_path: Path):
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    return db.connect(db_path), db_path


def _stale_iso(days: int = 30) -> str:
    """ISO timestamp *days* ago in UTC."""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat(timespec="seconds")


def _git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a git command, capturing output. Raises on non-zero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Scenario A: calibration adjustment fires (deterministic)
# ---------------------------------------------------------------------------

def test_calibration_adjustment_fires(tmp_path):
    """Record enough misses to push a reviewer below the FLOOR; assert adjust_trust fires."""
    conn, _ = _mk_conn(tmp_path)
    try:
        role = "test-reviewer"
        # Laplace floor is 0.4; with add-one smoothing and 10 misses:
        # score = (0+1)/(10+2) = 0.083, well below FLOOR=0.4.
        for _ in range(10):
            calibration.record_outcome(conn, role, hit=False)

        result = calibration.adjust_trust(conn, role)

        assert result["adjusted"] is True, "adjust_trust should have fired"
        assert result["distrusted"] == 1, "reviewer should be marked distrusted"
        c = calibration.get_calibration(conn, role)
        assert c["distrusted"] == 1
        assert c["score"] < calibration.FLOOR
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scenario B: weeding surfaces a stale spec (deterministic)
# ---------------------------------------------------------------------------

def test_weeding_surfaces_stale_spec(tmp_path):
    """A dispatched Spec with last_touched 30 days ago is flagged by flag_stale_specs."""
    conn, _ = _mk_conn(tmp_path)
    try:
        spec_id = nodes.create_node(
            conn, "Spec",
            status="dispatched",
            owner="test",
            body="stale spec body",
            criteria_json=json.dumps([{"text": "criterion", "verify": "true"}]),
            feedback_loop="open a retro on failure",
        )
        # Force last_touched to 30 days ago so the 14-day threshold fires.
        conn.execute(
            "UPDATE spec SET last_touched=? WHERE id=?",
            (_stale_iso(days=30), spec_id),
        )
        conn.commit()

        flagged = weeding.flag_stale_specs(conn, days=14)

        assert spec_id in flagged, f"spec {spec_id} should appear in flagged list"
        # Confirm the timestamp was stamped on the spec row.
        row = conn.execute(
            "SELECT stale_flagged_at FROM spec WHERE id=?", (spec_id,)
        ).fetchone()
        assert row is not None and row[0] is not None, "stale_flagged_at should be set"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scenario C: two orthogonal specs build in parallel + merge (LIVE)
# ---------------------------------------------------------------------------

def _setup_git_repo(repo: Path) -> None:
    """Initialise a bare git repo with an initial commit so worktrees can be created."""
    _git(["init", "-b", "main"], cwd=str(repo))
    _git(["config", "user.name", "Test Runner"], cwd=str(repo))
    _git(["config", "user.email", "test@example.com"], cwd=str(repo))
    # An initial commit is required before `git worktree add -b` will succeed.
    readme = repo / "README.txt"
    readme.write_text("agentic e2e base", encoding="utf-8")
    _git(["add", "README.txt"], cwd=str(repo))
    _git(["commit", "-m", "init: base commit for e2e test"], cwd=str(repo))


def _make_launch_fn(task_files: dict, mcp_config: Path, timeout: int = 1200):
    """Return a launch_fn that drives claude with a concrete file-creation prompt.

    The default _real_launch uses a generic placeholder prompt that won't
    reliably create a named file in the worktree. We override it here with a
    self-contained prompt that names the exact file to create, its content, and
    the commit step. *task_files* maps each task id to the filename that task
    must produce, so the prompt never has to read the graph DB.
    """
    def _launch(job: dict) -> dict:
        tid = job["task_id"]
        wt = job["worktree"]
        target = task_files[tid]
        prompt = (
            f"You are a builder agent working in a git worktree. "
            f"Your task id is {tid}. "
            f"Create a file named {target} in the current directory "
            f"with the content 'OK', then commit it with message 'feat: task {tid}'. "
            f"Use git add {target} then git commit. Do not use git push. Stop after committing."
        )
        try:
            # Pass mcp_config so the agent can reach the MCP server if it needs to.
            headless.run_claude_headless(
                prompt, cwd=wt, timeout=timeout, mcp_config=mcp_config
            )
            # Verify a commit was actually made (get HEAD sha).
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=wt, capture_output=True, text=True, check=True,
            ).stdout.strip()
            return {"task_id": tid, "ok": True, "sha": sha}
        except Exception as exc:  # noqa: BLE001 - Pool must not re-raise
            return {"task_id": tid, "ok": False, "error": str(exc)}

    return _launch


@pytest.mark.skipif(
    not headless.claude_on_path(),
    reason="live claude CLI not on PATH",
)
def test_parallel_specs_build_and_merge(tmp_path):
    """Two orthogonal Specs build in parallel worktrees and merge without collision."""
    # --- 1. Real git repo with an initial commit ----------------------------
    repo = tmp_path / "repo"
    repo.mkdir()
    _setup_git_repo(repo)

    # --- 2. Graph DB + MCP config ------------------------------------------
    conn, db_path = _mk_conn(tmp_path)
    mcp_cfg = headless.stage_mcp_config(repo, db_path)

    # --- 3. Two dispatched Specs, each with one Task having disjoint scope --
    spec_a = nodes.create_node(
        conn, "Spec",
        status="dispatched",
        owner="e2e",
        body="Spec A: create fileA.txt",
        criteria_json=json.dumps([{"text": "fileA.txt exists containing OK", "verify": "true"}]),
        feedback_loop="open a retro on failure",
    )
    spec_b = nodes.create_node(
        conn, "Spec",
        status="dispatched",
        owner="e2e",
        body="Spec B: create fileB.txt",
        criteria_json=json.dumps([{"text": "fileB.txt exists containing OK", "verify": "true"}]),
        feedback_loop="open a retro on failure",
    )

    # Tasks have disjoint scopes so detect_overlap allows both in the same batch.
    task_a = nodes.create_node(
        conn, "Task",
        status="pending",
        owner="e2e",
        body="create fileA.txt containing the word OK",
        tags=json.dumps(["fileA.txt"]),
    )
    task_b = nodes.create_node(
        conn, "Task",
        status="pending",
        owner="e2e",
        body="create fileB.txt containing the word OK",
        tags=json.dumps(["fileB.txt"]),
    )
    # Link each Task to its Spec via 'implements'.
    relations.link_nodes(conn, task_a, spec_a, "implements")
    relations.link_nodes(conn, task_b, spec_b, "implements")

    # --- 4. Custom launch_fn with concrete prompt ---------------------------
    task_files = {task_a: "fileA.txt", task_b: "fileB.txt"}
    launch_fn = _make_launch_fn(task_files, mcp_cfg, timeout=1200)

    # Stub review_fn: return CLEAN with calibrate=False (don't pollute calibration).
    def _review_clean(conn_, tid, job_result):
        return {"verdict": "CLEAN", "reviewer": "code-reviewer",
                "hit": True, "calibrate": False}

    # --- 5. Run the real tick with real git seams ---------------------------
    try:
        result = orchestrate.tick(
            conn,
            repo=str(repo),
            pool_size=2,
            launch_fn=launch_fn,
            worktree_factory=orchestrate._real_worktree,
            merge_fn=orchestrate._real_merge,
            review_fn=_review_clean,
        )
    finally:
        # Clean up worktrees so git does not complain on tmp_path teardown.
        try:
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(repo), capture_output=True,
            )
        except Exception:
            pass
        # Close the tick connection BEFORE reopening for assertions: on Windows
        # an agent subprocess may still hold a handle, so we want a clean single
        # reader (conn2) for the final reads rather than two live connections.
        conn.close()

    # --- 6. Assertions (structured state only; no prose inspection) ---------
    dispatched = set(result["dispatched"])
    merged = set(result["merged"])
    failed = result["failed"]
    escalations = result["escalations"]

    assert {task_a, task_b} <= dispatched, (
        f"Both tasks should be dispatched; got dispatched={dispatched}, "
        f"failed={failed}"
    )
    assert {task_a, task_b} <= merged, (
        f"Both tasks should merge; got merged={merged}, "
        f"escalations={escalations}, failed={failed}"
    )
    assert not failed, f"No task should fail; failed={failed}"
    assert not escalations, f"No merge conflicts expected; escalations={escalations}"

    # Both output files must exist in the repo working tree after merge.
    assert (repo / "fileA.txt").exists(), "fileA.txt missing after merge"
    assert (repo / "fileB.txt").exists(), "fileB.txt missing after merge"

    # Task statuses must be 'merged'; claims must be 'released'.
    conn2 = db.connect(db_path)
    try:
        for tid in (task_a, task_b):
            node = nodes.get_node(conn2, tid)
            assert node is not None
            assert node["status"] == "merged", f"task {tid} status={node['status']}"

            claim_rows = conn2.execute(
                "SELECT status FROM claim WHERE task_id=?", (tid,)
            ).fetchall()
            statuses = [r[0] for r in claim_rows]
            assert "released" in statuses, f"task {tid} claim not released: {statuses}"
    finally:
        conn2.close()

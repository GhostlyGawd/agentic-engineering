"""Orchestrator tick integration tests.

Most tests stub every external seam - NO real claude, NO real git. The graph is
built with nodes.create_node + relations.link_nodes; the tick is driven through
the injected seam closures so the test asserts on the composition wiring, not on
the behavior of the already-tested components. One test exercises the real
_real_worktree seam against a temp `git init` repo (git is available; only
`claude` is not), so it does NOT carry the llm marker.
"""
import json
import shutil
import subprocess

import pytest

from agentic_mcp import calibration, db, nodes, orchestrate, relations


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def _dispatched_spec(conn):
    return nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="s",
        criteria_json=json.dumps([{"text": "c", "verify": "pytest x"}]),
        feedback_loop="if a user reports a bug we open a PR and write a retro",
        dispatched_at="2026-05-23T00:00:00+00:00",
    )


def _task(conn, spec_id, scope_paths, status="pending"):
    tid = nodes.create_node(
        conn, "Task", status=status, owner="t", body="task",
        tags=json.dumps(scope_paths),
    )
    relations.link_nodes(conn, tid, spec_id, "implements")  # Task implements Spec
    return tid


# --- stub seams (closures) -------------------------------------------------
def fake_worktree(repo, tid):
    return (f"/wt/{tid}", f"orch/{tid}")


def fake_merge_ok(repo, branch):
    return None


def fake_launch_ok(job):
    return {"task_id": job["task_id"], "ok": True, "sha": "deadbeef"}


def fake_review_clean(conn, tid, r):
    return {"verdict": "CLEAN", "reviewer": "code-reviewer", "hit": True}


def _claim_status(conn, task_id):
    rows = conn.execute(
        "SELECT status FROM claim WHERE task_id=?", (task_id,)
    ).fetchall()
    return [r[0] for r in rows]


# --- 1. smoke --------------------------------------------------------------
def test_tick_smoke_returns_summary(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        _task(conn, spec, ["src/a/*"])
        result = orchestrate.tick(
            conn, repo=".", pool_size=3,
            launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        for key in ("weeded", "dispatched", "merged", "failed",
                    "escalations", "calibrated"):
            assert key in result
            assert isinstance(result[key], list)
    finally:
        conn.close()


# --- 2. two disjoint tasks both dispatched + merged ------------------------
def test_disjoint_tasks_both_dispatched_and_merged(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        t2 = _task(conn, spec, ["src/b/*"])
        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert set(result["dispatched"]) == {t1, t2}
        assert set(result["merged"]) == {t1, t2}
        # claims released, task statuses merged
        for t in (t1, t2):
            assert _claim_status(conn, t) == ["released"]
            assert nodes.get_node(conn, t)["status"] == "merged"
    finally:
        conn.close()


# --- 3. overlapping scope -> only one dispatched ---------------------------
def test_overlapping_tasks_only_one_dispatched(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        t2 = _task(conn, spec, ["src/a/*"])
        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert len(result["dispatched"]) == 1
        assert result["dispatched"][0] in {t1, t2}
    finally:
        conn.close()


# --- 4. launch failure -> failed, reset to pending, claim released ---------
def test_launch_failure_resets_to_pending_and_releases_claim(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def fake_launch_fail(job):
            return {"task_id": job["task_id"], "ok": False, "error": "boom"}

        result = orchestrate.tick(
            conn, launch_fn=fake_launch_fail, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert t1 in result["failed"]
        assert t1 not in result["merged"]
        # Recovered like NEEDS_FIXING: re-enterable next tick, scope freed.
        assert nodes.get_node(conn, t1)["status"] == "pending"
        assert _claim_status(conn, t1) == ["released"]
    finally:
        conn.close()


# --- NEEDS_FIXING resets the task so it re-enters next tick ----------------
def test_needs_fixing_resets_task_to_pending_and_releases_claim(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def fake_review_needs_fixing(conn_, tid, r):
            return {"verdict": "NEEDS_FIXING", "reviewer": "code-reviewer",
                    "hit": False}

        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_needs_fixing,
        )
        assert t1 not in result["merged"]
        assert t1 not in result["failed"]
        assert nodes.get_node(conn, t1)["status"] == "pending"  # re-enterable
        assert _claim_status(conn, t1) == ["released"]
    finally:
        conn.close()


# --- merge conflict -> escalation, claim stays held ------------------------
def test_merge_failure_escalates_and_keeps_claim_held(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def fake_merge_raises(repo, branch):
            raise RuntimeError("merge conflict")

        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_raises, review_fn=fake_review_clean,
        )
        esc_ids = {e["task_id"] for e in result["escalations"]}
        assert t1 in esc_ids
        assert t1 not in result["merged"]
        assert nodes.get_node(conn, t1)["status"] != "merged"
        assert _claim_status(conn, t1) == ["held"]
    finally:
        conn.close()


# --- 5. contrarian reviewer pushed below floor -> calibration fires --------
def test_distrusted_reviewer_appears_in_calibrated(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        # Pre-load misses so a single tick's record_outcome pushes below FLOOR.
        for _ in range(10):
            calibration.record_outcome(conn, "contrarian", hit=False)

        def fake_review_contrarian(conn_, tid, r):
            return {"verdict": "CLEAN", "reviewer": "contrarian", "hit": False}

        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_contrarian,
        )
        assert "contrarian" in result["calibrated"]
        assert calibration.get_calibration(conn, "contrarian")["distrusted"] == 1
        assert t1 in result["merged"]  # CLEAN verdict still merges
    finally:
        conn.close()


# --- 6. dependent tasks merge in DAG order ---------------------------------
def test_merge_order_respects_depends_on_edge(tmp_db_path):
    """t2 depends-on t1 -> across ticks, t1's branch merges before t2's.

    ready_tasks gates t2 on t1's status, so the two cannot co-dispatch while
    t1 is unresolved. The dependency ordering therefore plays out over two
    ticks: tick 1 merges t1 (status -> 'merged', a resolved status), which
    unblocks t2 for tick 2. Asserting the recorded merge_fn call order shows
    the orchestrator never merges a dependent ahead of its prerequisite.
    """
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        t2 = _task(conn, spec, ["src/b/*"])
        relations.link_nodes(conn, t2, t1, "depends-on")
        merged_branches = []

        def fake_merge_record(repo, branch):
            merged_branches.append(branch)

        # Tick 1: only t1 ready (t2 blocked by unresolved t1).
        r1 = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_record, review_fn=fake_review_clean,
        )
        assert r1["merged"] == [t1]
        # Tick 2: t1 is now 'merged' (a resolved status) -> t2 becomes ready.
        r2 = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_record, review_fn=fake_review_clean,
        )
        assert r2["merged"] == [t2]
        # Global merge order honors the dependency: t1 before t2.
        assert merged_branches == [f"orch/{t1}", f"orch/{t2}"]
    finally:
        conn.close()


# --- 7. CLI smoke ----------------------------------------------------------
def test_cli_main_prints_json(tmp_db_path, monkeypatch, capsys):
    db.init_db(tmp_db_path)  # empty graph
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_db_path))
    monkeypatch.setattr("sys.argv", ["orchestrate", "--once"])
    rc = orchestrate.main()
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["dispatched"] == []
    assert payload["weeded"] == []
    assert rc in (0, None)


# --- worktree setup failure must not crash the tick -----------------------
def test_tick_does_not_raise_when_worktree_factory_fails(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def boom_worktree(repo, tid):
            raise RuntimeError("git worktree add exploded")

        # Must NOT raise.
        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=boom_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert t1 in result["failed"]
        assert t1 not in result["dispatched"]
        assert t1 not in result["merged"]
        # Claim was released (or never left held) so the scope is not stranded.
        assert _claim_status(conn, t1) in (["released"], [])
    finally:
        conn.close()


# --- real-git: _real_worktree is idempotent across re-dispatch ------------
@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_real_worktree_idempotent_on_redispatch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args],
                       check=True, capture_output=True, text=True)

    git("init")
    git("config", "user.email", "t@t.test")
    git("config", "user.name", "t")
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "init")

    # First dispatch creates the worktree + branch.
    path1, branch1 = orchestrate._real_worktree(str(repo), "t1")
    # Second dispatch (re-enter after NEEDS_FIXING / failure) must NOT raise -
    # the helper cleans the prior attempt and recreates.
    path2, branch2 = orchestrate._real_worktree(str(repo), "t1")
    assert path1 == path2
    assert branch1 == branch2 == "orch/t1"


def test_stale_node_surfaced_readonly(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        nid = nodes.create_node(conn, "Goal", status="open", owner="t", body="b")
        # Backdate last_touched well past the default 14-day threshold.
        conn.execute("UPDATE goal SET last_touched=? WHERE id=?",
                     ("2000-01-01T00:00:00+00:00", nid))
        conn.commit()
        before = nodes.get_node(conn, nid)
        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert nid in result["stale_nodes"]
        after = nodes.get_node(conn, nid)
        assert after["status"] == before["status"]           # not auto-closed
        assert after["last_touched"] == before["last_touched"]  # not touched
    finally:
        conn.close()


def test_fresh_node_not_surfaced(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        nid = nodes.create_node(conn, "Goal", status="open", owner="t", body="b")
        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert nid not in result["stale_nodes"]
    finally:
        conn.close()


def test_retry_cap_escalates_on_third_failure(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def fail(job):
            return {"task_id": job["task_id"], "ok": False, "error": "boom"}

        for _ in range(2):  # strikes 1 and 2 -> pending
            orchestrate.tick(conn, launch_fn=fail, worktree_factory=fake_worktree,
                             merge_fn=fake_merge_ok, review_fn=fake_review_clean)
            assert nodes.get_node(conn, t1)["status"] == "pending"

        r3 = orchestrate.tick(conn, launch_fn=fail, worktree_factory=fake_worktree,
                              merge_fn=fake_merge_ok, review_fn=fake_review_clean)
        assert nodes.get_node(conn, t1)["status"] == "escalated"
        assert t1 in {e["task_id"] for e in r3["escalations"]}
        loop = orchestrate._find_open_dispatch_loop(conn, t1)
        assert loop["iteration_count"] == 3
        assert loop["diagnostic_fired_at"] is not None
    finally:
        conn.close()


def test_escalated_task_not_redispatched(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def fail(job):
            return {"task_id": job["task_id"], "ok": False, "error": "boom"}

        for _ in range(3):
            orchestrate.tick(conn, launch_fn=fail, worktree_factory=fake_worktree,
                             merge_fn=fake_merge_ok, review_fn=fake_review_clean)
        assert nodes.get_node(conn, t1)["status"] == "escalated"
        r = orchestrate.tick(conn, launch_fn=fake_launch_ok,
                             worktree_factory=fake_worktree,
                             merge_fn=fake_merge_ok, review_fn=fake_review_clean)
        assert t1 not in r["dispatched"]
    finally:
        conn.close()


def test_repeated_needs_fixing_escalates_on_third(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def needs_fixing(conn_, tid, r):
            return {"verdict": "NEEDS_FIXING", "reviewer": "code-reviewer",
                    "hit": False}

        for _ in range(2):
            orchestrate.tick(conn, launch_fn=fake_launch_ok,
                             worktree_factory=fake_worktree,
                             merge_fn=fake_merge_ok, review_fn=needs_fixing)
            assert nodes.get_node(conn, t1)["status"] == "pending"
        orchestrate.tick(conn, launch_fn=fake_launch_ok,
                         worktree_factory=fake_worktree,
                         merge_fn=fake_merge_ok, review_fn=needs_fixing)
        assert nodes.get_node(conn, t1)["status"] == "escalated"
    finally:
        conn.close()


def test_failure_then_success_resolves_loop(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        calls = {"n": 0}

        def flaky(job):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"task_id": job["task_id"], "ok": False, "error": "boom"}
            return {"task_id": job["task_id"], "ok": True, "sha": "deadbeef"}

        orchestrate.tick(conn, launch_fn=flaky, worktree_factory=fake_worktree,
                         merge_fn=fake_merge_ok, review_fn=fake_review_clean)
        assert orchestrate._find_open_dispatch_loop(conn, t1) is not None

        r2 = orchestrate.tick(conn, launch_fn=flaky, worktree_factory=fake_worktree,
                              merge_fn=fake_merge_ok, review_fn=fake_review_clean)
        assert t1 in r2["merged"]
        assert orchestrate._find_open_dispatch_loop(conn, t1) is None
    finally:
        conn.close()

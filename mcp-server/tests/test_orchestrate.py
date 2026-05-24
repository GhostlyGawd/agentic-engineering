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
import types

import pytest

from agentic_mcp import calibration, claims, db, findings, nodes, orchestrate, relations


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
    return {"task_id": job["task_id"], "ok": True, "sha": "deadbeef",
            "worktree": job["worktree"]}


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
        # Intentional double-surface: an escalating launch failure appears in
        # both `failed` (this tick's failure) and `escalations` (terminal state).
        assert t1 in r3["failed"]
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


def test_integration_branch_match_merges(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
            integration_branch="main", current_branch_fn=lambda repo: "main",
        )
        assert t1 in result["merged"]
    finally:
        conn.close()


def test_clean_task_blocked_by_branch_guard_resolves_dispatch_loop(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def fail_once(job):
            return {"task_id": job["task_id"], "ok": False, "error": "boom"}

        # Tick 1: fail -> open dispatch loop at count 1, task back to pending.
        orchestrate.tick(conn, launch_fn=fail_once, worktree_factory=fake_worktree,
                         merge_fn=fake_merge_ok, review_fn=fake_review_clean)
        loop = orchestrate._find_open_dispatch_loop(conn, t1)
        assert loop is not None and loop["iteration_count"] == 1

        # Tick 2: launch ok + review CLEAN, but HEAD != integration branch.
        merged_calls = []
        r2 = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=lambda repo, b: merged_calls.append(b),
            review_fn=fake_review_clean,
            integration_branch="main", current_branch_fn=lambda repo: "feature-x",
        )
        # Branch guard blocked the merge...
        assert merged_calls == []
        assert t1 in {e["task_id"] for e in r2["escalations"]}
        # Tick 1's failed claim was released; tick 2's claim is still held (the
        # guard does not release it). So the task carries one released + one held
        # claim - assert the LIVE claim is held, not the full historical list.
        assert "held" in _claim_status(conn, t1)
        assert nodes.get_node(conn, t1)["status"] == "in_progress"
        # ...but build+review succeeded, so the dispatch loop is resolved.
        assert orchestrate._find_open_dispatch_loop(conn, t1) is None

        # Operator resets the parked task (status -> pending AND the held claim
        # released so the scope is free to re-dispatch); a fresh failure starts a
        # NEW loop at count 1 (strike budget intact - not drifted to 2 by a stale
        # loop).
        nodes.update_node(conn, t1, status="pending")
        held = conn.execute(
            "SELECT id FROM claim WHERE task_id=? AND status='held'", (t1,)
        ).fetchone()
        claims.release_claim(conn, held[0])
        orchestrate.tick(conn, launch_fn=fail_once, worktree_factory=fake_worktree,
                         merge_fn=fake_merge_ok, review_fn=fake_review_clean)
        loop3 = orchestrate._find_open_dispatch_loop(conn, t1)
        assert loop3 is not None and loop3["iteration_count"] == 1
    finally:
        conn.close()


def test_integration_branch_mismatch_skips_and_escalates(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        merged_calls = []
        result = orchestrate.tick(
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=lambda r, b: merged_calls.append(b),
            review_fn=fake_review_clean,
            integration_branch="main",
            current_branch_fn=lambda repo: "feature-x",
        )
        assert result["merged"] == []
        assert merged_calls == []  # merge_fn never called
        assert t1 in {e["task_id"] for e in result["escalations"]}
        assert _claim_status(conn, t1) == ["held"]  # held for a later correct tick
    finally:
        conn.close()


def test_integration_branch_none_is_default_behavior(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        result = orchestrate.tick(  # no integration_branch -> merges regardless
            conn, launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert t1 in result["merged"]
    finally:
        conn.close()


# --- _verdict_from_graph -------------------------------------------------
def test_verdict_from_graph_clean_when_no_open_critical(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        rv = orchestrate._verdict_from_graph(conn, spec)
        assert rv["verdict"] == "CLEAN"
        assert rv["reviewer"] == "code-reviewer"
        assert rv["hit"] is True
        assert rv["calibrate"] is False
    finally:
        conn.close()


def test_verdict_from_graph_needs_fixing_when_open_critical(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        findings.log_finding(conn, parent_id=spec, severity="Critical",
                             body="criterion 0 failed")
        rv = orchestrate._verdict_from_graph(conn, spec)
        assert rv["verdict"] == "NEEDS_FIXING"
    finally:
        conn.close()


def test_verdict_from_graph_ignores_resolved_critical(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        fid = findings.log_finding(conn, parent_id=spec, severity="Critical",
                                   body="was failing")
        nodes.update_node(conn, fid, status="resolved")
        rv = orchestrate._verdict_from_graph(conn, spec)
        assert rv["verdict"] == "CLEAN"
    finally:
        conn.close()


def test_verdict_from_graph_ignores_other_specs_critical(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec_a = _dispatched_spec(conn)
        spec_b = _dispatched_spec(conn)
        findings.log_finding(conn, parent_id=spec_b, severity="Critical",
                             body="b is broken")
        rv = orchestrate._verdict_from_graph(conn, spec_a)
        assert rv["verdict"] == "CLEAN"
    finally:
        conn.close()


def test_verdict_from_graph_ignores_open_important(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        findings.log_finding(conn, parent_id=spec, severity="Important",
                             body="non-blocking nit")
        rv = orchestrate._verdict_from_graph(conn, spec)
        assert rv["verdict"] == "CLEAN"
    finally:
        conn.close()


# --- _build_builder_prompt -----------------------------------------------
def _spec_with_criteria(conn, criteria):
    return nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="spec body",
        criteria_json=json.dumps(criteria),
        feedback_loop="open a retro on failure",
    )


def test_build_builder_prompt_contains_task_body_and_criteria(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _spec_with_criteria(conn, [
            {"text": "alpha criterion holds", "verify": "pytest a"},
            {"text": "beta criterion holds", "verify": "pytest b"},
        ])
        tid = nodes.create_node(conn, "Task", status="pending", owner="t",
                                body="DO THE ALPHA THING", tags=json.dumps(["src/a/*"]))
        relations.link_nodes(conn, tid, spec, "implements")

        prompt = orchestrate._build_builder_prompt(conn, tid)

        assert "DO THE ALPHA THING" in prompt
        assert "alpha criterion holds" in prompt
        assert "beta criterion holds" in prompt
        assert tid in prompt
        assert spec in prompt
    finally:
        conn.close()


def test_build_builder_prompt_handles_missing_spec(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        tid = nodes.create_node(conn, "Task", status="pending", owner="t",
                                body="ORPHAN TASK", tags=json.dumps(["src/a/*"]))
        # No implements edge.
        prompt = orchestrate._build_builder_prompt(conn, tid)
        assert "ORPHAN TASK" in prompt
        assert "(none)" in prompt
    finally:
        conn.close()


def test_build_builder_prompt_tolerates_malformed_criteria(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        # criteria_json is valid JSON but the wrong shape (not a list of dicts).
        spec = _spec_with_criteria(conn, ["not a dict"])
        tid = nodes.create_node(conn, "Task", status="pending", owner="t",
                                body="ROBUST TASK", tags=json.dumps(["src/a/*"]))
        relations.link_nodes(conn, tid, spec, "implements")
        prompt = orchestrate._build_builder_prompt(conn, tid)  # must not raise
        assert "ROBUST TASK" in prompt
        assert "(none)" in prompt  # no valid criteria -> placeholder
    finally:
        conn.close()


# --- _real_launch (claude + git monkeypatched) ---------------------------
def test_real_launch_runs_prompt_and_returns_worktree(monkeypatch):
    calls = {}

    def fake_run(prompt, cwd, timeout=900, mcp_config=None):
        calls["prompt"] = prompt
        calls["cwd"] = cwd
        calls["mcp_config"] = mcp_config
        return {"result": "built"}

    monkeypatch.setattr(orchestrate.headless, "run_claude_headless", fake_run)
    monkeypatch.setattr(orchestrate, "_git",
                        lambda args: types.SimpleNamespace(stdout="abc123\n"))

    job = {"task_id": "t1", "worktree": "/wt/t1", "branch": "orch/t1",
           "prompt": "BUILD THIS", "mcp_config": "/repo/.mcp.json"}
    out = orchestrate._real_launch(job)

    assert out == {"task_id": "t1", "ok": True, "sha": "abc123",
                   "worktree": "/wt/t1"}
    assert calls["prompt"] == "BUILD THIS"
    assert calls["cwd"] == "/wt/t1"
    assert calls["mcp_config"] == "/repo/.mcp.json"


def test_real_launch_folds_exception_into_error(monkeypatch):
    def boom(prompt, cwd, timeout=900, mcp_config=None):
        raise RuntimeError("claude exploded")

    monkeypatch.setattr(orchestrate.headless, "run_claude_headless", boom)
    job = {"task_id": "t1", "worktree": "/wt/t1", "branch": "orch/t1",
           "prompt": "BUILD THIS", "mcp_config": None}
    out = orchestrate._real_launch(job)
    assert out["task_id"] == "t1"
    assert out["ok"] is False
    assert "claude exploded" in out["error"]


# --- _real_review (claude monkeypatched; verdict from graph) --------------
def test_real_review_clean_when_no_open_critical(tmp_db_path, monkeypatch):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        seen = {}

        def fake_run(prompt, cwd, timeout=900, mcp_config=None):
            seen["prompt"] = prompt
            seen["cwd"] = cwd
            seen["timeout"] = timeout
            seen["mcp_config"] = mcp_config
            return {"result": "reviewed"}

        monkeypatch.setattr(orchestrate.headless, "run_claude_headless", fake_run)
        rv = orchestrate._real_review(
            conn, t1, {"worktree": "/wt/t1", "mcp_config": "/repo/.mcp.json"})

        assert rv["verdict"] == "CLEAN"
        assert rv["calibrate"] is False
        assert seen["cwd"] == "/wt/t1"
        assert seen["mcp_config"] == "/repo/.mcp.json"
        assert seen["timeout"] == 1800
        assert spec in seen["prompt"]
        assert "review-pr" in seen["prompt"]
    finally:
        conn.close()


def test_real_review_needs_fixing_when_open_critical(tmp_db_path, monkeypatch):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        findings.log_finding(conn, parent_id=spec, severity="Critical",
                             body="criterion failed")
        monkeypatch.setattr(orchestrate.headless, "run_claude_headless",
                            lambda *a, **k: {"result": "reviewed"})
        rv = orchestrate._real_review(
            conn, t1, {"worktree": "/wt/t1", "mcp_config": None})
        assert rv["verdict"] == "NEEDS_FIXING"
    finally:
        conn.close()


def test_real_review_needs_fixing_on_claude_failure(tmp_db_path, monkeypatch):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def boom(*a, **k):
            raise RuntimeError("review-pr timed out")

        monkeypatch.setattr(orchestrate.headless, "run_claude_headless", boom)
        rv = orchestrate._real_review(
            conn, t1, {"worktree": "/wt/t1", "mcp_config": None})
        assert rv["verdict"] == "NEEDS_FIXING"
    finally:
        conn.close()


def test_real_review_needs_fixing_when_task_has_no_spec(tmp_db_path, monkeypatch):
    conn = _mk_conn(tmp_db_path)
    try:
        t1 = nodes.create_node(conn, "Task", status="pending", owner="t",
                               body="orphan", tags=json.dumps(["src/a/*"]))
        # No implements edge -> neighbors()[0] would IndexError; must be caught.
        monkeypatch.setattr(orchestrate.headless, "run_claude_headless",
                            lambda *a, **k: {"result": "reviewed"})
        rv = orchestrate._real_review(
            conn, t1, {"worktree": "/wt/t1", "mcp_config": None})
        assert rv["verdict"] == "NEEDS_FIXING"
    finally:
        conn.close()


# --- tick() wiring: prompt assembly + mcp staging ------------------------
def test_tick_assembles_prompt_into_job(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        captured = {}

        def capture_launch(job):
            captured[job["task_id"]] = job
            return {"task_id": job["task_id"], "ok": True, "sha": "x",
                    "worktree": job["worktree"]}

        orchestrate.tick(
            conn, launch_fn=capture_launch, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        job = captured[t1]
        assert "prompt" in job
        assert "task" in job["prompt"]  # body of _task() is "task"
        # No db_path -> no staging -> mcp_config is None (or absent).
        assert job.get("mcp_config") is None
    finally:
        conn.close()


def test_tick_stages_mcp_config_when_db_path_set(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        captured = {}

        def capture_launch(job):
            captured[job["task_id"]] = job
            return {"task_id": job["task_id"], "ok": True, "sha": "x",
                    "worktree": job["worktree"]}

        orchestrate.tick(
            conn, repo=str(repo), db_path=db_path,
            launch_fn=capture_launch, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert (repo / ".mcp.json").exists()
        assert captured[t1]["mcp_config"] == repo / ".mcp.json"
    finally:
        conn.close()


def test_tick_no_mcp_stage_when_no_jobs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        # Empty graph: no tasks -> no jobs -> must NOT write .mcp.json.
        orchestrate.tick(
            conn, repo=str(repo), db_path=db_path,
            launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert not (repo / ".mcp.json").exists()
    finally:
        conn.close()


def test_tick_enriches_review_input_with_worktree_and_mcp(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        seen = {}

        def review_capture(conn_, tid, job_result):
            seen[tid] = dict(job_result)
            return {"verdict": "CLEAN", "reviewer": "code-reviewer",
                    "hit": True, "calibrate": False}

        orchestrate.tick(
            conn, repo=str(repo), db_path=db_path,
            launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=review_capture,
        )
        assert seen[t1]["worktree"] == f"/wt/{t1}"
        assert seen[t1]["mcp_config"] == repo / ".mcp.json"
    finally:
        conn.close()

"""Stateless orchestrator tick - the Phase 2 pipeline composed end to end.

One tick(): weed stale specs, pick a disjoint-scope batch of ready tasks, claim
their scopes, dispatch builder agents through the headless Pool, review +
calibrate each result, merge CLEAN tasks in dependency order, and surface
failures/escalations. tick() is the only place the Phase 2 components are wired
together; every component it calls is independently tested.

Seams (launch_fn, worktree_factory, merge_fn, review_fn) are injectable so fast
tests stub out the real `claude` and `git` invocations entirely. Production uses
the _real_* defaults below. tick() is stateless: all durable state lives in the
graph DB passed in; nothing is cached between ticks.

Contract guarantee: tick() MUST NOT raise for normal worker/review/merge
failures - those become entries in result["failed"]/result["escalations"]. Only
genuine programming errors propagate. Worker/review/setup failures now accrue
strikes on a per-task CriticalLoop and escalate on the 3rd (status `escalated`)
rather than re-dispatching indefinitely.

Integration-branch assumption: _real_merge merges each worktree branch into the
repo's CURRENTLY-CHECKED-OUT branch, assumed to be the integration branch
(HEAD == integration branch). The deployment is responsible for checking out
that branch before running ticks. Enforcement is now available OPT-IN via
tick(integration_branch=...) / --integration-branch: on a HEAD mismatch the tick
skips ALL merges and escalates each CLEAN task. The default (None) preserves the
documented-only assumption (merge into whatever HEAD is checked out).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import (
    calibration, claims, db, findings, headless, loops, nodes, relations,
    scheduler, weeding,
)


# --- scope parsing ---------------------------------------------------------
def task_scope(task: dict) -> list[str]:
    """Path globs a task will touch, from its JSON `tags` array.

    Absent / unparseable / empty -> ["**"], which overlaps every other scope
    and so forces the task to run serially. That is the safe default: better to
    serialize an unscoped task than to let two workers collide on disk.
    """
    raw = task.get("tags")
    if not raw:
        return ["**"]
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return ["**"]
    if isinstance(parsed, list) and parsed:
        return [str(p) for p in parsed]
    return ["**"]


# --- real seams (kept small; tests inject stubs) ---------------------------
_BUILDER_PROMPT = (
    "You are a builder agent. Implement the assigned task in this worktree, "
    "commit your work, then stop."
)


def _git(args: list[str]) -> subprocess.CompletedProcess:
    # No shell=True; capture_output handles native-exe stderr fine on this box.
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _real_launch(job: dict) -> dict:
    """Run one builder agent headless, return a structured result.

    MUST catch its own exceptions: headless.Pool re-raises whatever launch_fn
    raises, which would abort the whole batch. So every failure is folded into
    {"ok": False, "error": ...} and the orchestrator routes it to `failed`.
    """
    tid = job["task_id"]
    try:
        headless.run_claude_headless(_BUILDER_PROMPT, cwd=job["worktree"])
        sha = _git(["-C", job["worktree"], "rev-parse", "HEAD"]).stdout.strip()
        return {"task_id": tid, "ok": True, "sha": sha}
    except Exception as e:  # noqa: BLE001 - launch_fn must never raise to the Pool
        return {"task_id": tid, "ok": False, "error": str(e)}


def _git_quiet(args: list[str]) -> None:
    """Best-effort git call - swallow failure (e.g. 'doesn't exist' on cleanup)."""
    subprocess.run(["git", *args], check=False, capture_output=True, text=True)


def _real_worktree(repo: str, task_id: str) -> tuple[str, str]:
    branch = "orch/" + task_id
    path = str(Path(repo) / ".worktrees" / task_id)
    # Idempotent: a re-dispatched task (NEEDS_FIXING / launch-failure reset to
    # pending) hits the same path+branch, and `git worktree add` fails if either
    # already exists. Best-effort remove any prior attempt first so re-dispatch
    # never crashes the tick; the cleanup calls are quiet (a "doesn't exist"
    # error on the first dispatch is expected and ignored).
    _git_quiet(["-C", repo, "worktree", "remove", "--force", path])
    _git_quiet(["-C", repo, "branch", "-D", branch])
    _git(["-C", repo, "worktree", "add", path, "-b", branch])
    return (path, branch)


def _real_merge(repo: str, branch: str) -> None:
    # Merges *branch* into the repo's CURRENTLY-CHECKED-OUT branch, which is
    # ASSUMED to be the integration branch (HEAD == integration branch). This
    # assumption is documented, not enforced - the orchestrator's deployment is
    # responsible for checking out the integration branch before running ticks.
    # check=True -> CalledProcessError on conflict, which tick() routes to
    # escalations (claim stays held so the next tick can retry / a human can act).
    _git(["-C", repo, "merge", "--no-ff", branch])


def _real_current_branch(repo: str) -> str:
    # The branch HEAD points at. Compared to integration_branch when that guard
    # is enabled; injectable so fast tests need no real git.
    return _git(["-C", repo, "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()


def _real_review(conn, task_id: str, job_result: dict) -> dict:
    """Minimal integration-default reviewer.

    Task 8's e2e overrides this with the real Phase-1 reviewer dispatch (spawn
    the code-reviewer agent, parse its verdict). Kept thin on purpose so this
    module composes cleanly without pulling in the review machinery.
    """
    # calibrate=False: this stub's hit=True is a placeholder, not a real review
    # outcome, so it must NOT bias code-reviewer's calibration on every tick.
    # Real reviewers (Task 8) omit the flag -> calibrate defaults True.
    return {"verdict": "CLEAN", "reviewer": "code-reviewer", "hit": True,
            "calibrate": False}


# --- retry cap (CriticalLoop-backed) ---------------------------------------
def _find_open_dispatch_loop(conn, task_id: str) -> dict | None:
    """The open CriticalLoop tracking this task's dispatch failures, or None.

    Linkage survives stateless ticks: a 'dispatch-failure' Finding has
    parent_id == task_id, and the loop's finding_id points back to it.
    """
    row = conn.execute(
        "SELECT cl.id FROM critical_loop cl "
        "JOIN finding f ON f.id = cl.finding_id "
        "WHERE f.parent_id = ? AND f.subtype = 'dispatch-failure' "
        "AND cl.status = 'open' "
        "ORDER BY cl.started_at LIMIT 1",
        (task_id,),
    ).fetchone()
    return nodes.get_node(conn, row[0]) if row else None


def _handle_failure(conn, task_id: str, claim_id: str, reason: str,
                    result: dict) -> None:
    """Record a dispatch failure; escalate on the 3rd strike, else reset to pending.

    Strike count lives in the CriticalLoop's iteration_count (schema default 1).
    First failure CREATES the loop (count = 1, no advance); each later failure
    advances it (1->2, 2->3). When advance pushes count to DIAGNOSTIC_THRESHOLD
    (3) the loop stamps diagnostic_fired_at and the task escalates instead of
    re-dispatching. Either way the claim is released so the scope is freed.
    """
    loop = _find_open_dispatch_loop(conn, task_id)
    if loop is None:
        fid = findings.log_finding(
            conn, parent_id=task_id, severity="Important",
            subtype="dispatch-failure", body=reason,
        )
        loop = nodes.get_node(conn, loops.start_critical_loop(conn, fid))
    else:
        loop = loops.advance_critical_loop(conn, loop["id"])

    claims.release_claim(conn, claim_id)
    if loop["diagnostic_fired_at"]:
        nodes.update_node(conn, task_id, status="escalated")
        result["escalations"].append({
            "task_id": task_id, "reason": reason,
            "iterations": loop["iteration_count"],
        })
    else:
        nodes.update_node(conn, task_id, status="pending")


# --- the tick --------------------------------------------------------------
def tick(
    conn,
    *,
    repo: str = ".",
    pool_size: int = 3,
    weed_days: int = 14,
    launch_fn=_real_launch,
    worktree_factory=_real_worktree,
    merge_fn=_real_merge,
    review_fn=_real_review,
    integration_branch: str | None = None,
    current_branch_fn=_real_current_branch,
) -> dict:
    result = {
        "weeded": [],
        "stale_nodes": [],
        "dispatched": [],
        "merged": [],
        "failed": [],
        "escalations": [],
        "calibrated": [],
    }

    # 1. Weed: flag stale dispatched specs (stamps stale_flagged_at) AND surface
    # stale non-terminal nodes for triage. find_stale_nodes is read-only by
    # contract - it never changes status or sets a flag; we only report ids.
    result["weeded"] = weeding.flag_stale_specs(conn, weed_days)
    result["stale_nodes"] = [n["id"] for n in weeding.find_stale_nodes(conn, weed_days)]

    # 2. Ready set.
    ready = scheduler.ready_tasks(conn)

    # 3. Disjoint-scope batch, capped at pool_size.
    candidates = [
        {"task_id": t["id"], "scope_paths": task_scope(t)} for t in ready
    ]
    batch = claims.detect_overlap(candidates)[:pool_size]

    # 4. Claim + mark in_progress + build jobs.
    claim_ids: dict[str, str] = {}
    branches: dict[str, str] = {}
    jobs: list[dict] = []
    for c in batch:
        tid = c["task_id"]
        scope_paths = c["scope_paths"]
        # Claim FIRST (cheap, conflict-detecting). detect_overlap only sees the
        # current ready set, NOT held claims from prior ticks, so claim_scope can
        # still conflict here (e.g. a task stuck in_progress holds an invisible
        # claim). Claiming before creating the worktree means a ClaimConflict
        # never leaves an orphaned worktree on disk.
        try:
            cid = claims.claim_scope(conn, tid, scope_paths)
        except claims.ClaimConflict:
            # An overlapping claim is already held; skip - do not dispatch.
            continue
        # Worktree creation + setup can fail (e.g. a re-dispatched task whose
        # worktree git refuses to recreate). ANY such failure must not crash the
        # tick: route the task to `failed`, release the claim we just took, and
        # move on. ClaimConflict is handled above; everything else lands here.
        try:
            wt, branch = worktree_factory(repo, tid)
            claims.attach_worktree(conn, cid, wt, branch)
            nodes.update_node(conn, tid, status="in_progress")
        except Exception as e:  # noqa: BLE001 - setup failure must never propagate
            _handle_failure(conn, tid, cid, f"worktree/setup failure: {e}", result)
            result["failed"].append(tid)
            continue
        claim_ids[tid] = cid
        branches[tid] = branch
        jobs.append({"task_id": tid, "worktree": wt, "branch": branch})
        result["dispatched"].append(tid)

    # 5. Dispatch through the pool (launch_fn never raises - see _real_launch).
    results = headless.Pool(max_workers=pool_size).run(jobs, launch_fn) if jobs else []

    # 6. Review + calibrate the successful results.
    clean_ids: list[str] = []
    for r in results:
        if not r.get("ok"):
            continue
        tid = r["task_id"]
        rv = review_fn(conn, tid, r)
        reviewer = rv["reviewer"]
        if rv.get("calibrate", True):
            calibration.record_outcome(conn, reviewer, rv["hit"])
            adj = calibration.adjust_trust(conn, reviewer)
            if adj["adjusted"] and reviewer not in result["calibrated"]:
                result["calibrated"].append(reviewer)
        if rv["verdict"] == "CLEAN":
            clean_ids.append(tid)
            # Build + review succeeded, so any open dispatch-failure loop for
            # this task is resolved NOW - not deferred to merge success. This
            # keeps the strike budget correct if the merge is then skipped (e.g.
            # integration-branch guard) or fails (merge conflict): a later reset
            # + failure starts a FRESH loop rather than advancing a stale one.
            recovered = _find_open_dispatch_loop(conn, tid)
            if recovered is not None:
                loops.resolve_critical_loop(conn, recovered["id"])
        else:
            _handle_failure(conn, tid, claim_ids[tid],
                            "NEEDS_FIXING review verdict", result)

    # 7. Merge CLEAN tasks in dependency (topological) order.
    # NOTE: within a SINGLE tick this edge set is always empty - ready_tasks
    # gates a dependent task until its prerequisite resolves, so two tasks with
    # a depends-on edge between them never land in the same CLEAN batch. Ordering
    # correctness therefore lives in CROSS-TICK sequencing (the prerequisite
    # merges first, which makes the dependent ready next tick). merge_order is
    # kept here for robustness/correctness if that invariant ever changes.
    # Integration-branch guard (opt-in). If HEAD is not the integration branch,
    # refuse to merge anything into the wrong branch: escalate every CLEAN task
    # and skip merging. Claims stay held and the tasks remain in_progress,
    # pending external recovery - same as the merge-conflict escalation path
    # (no automatic cross-tick retry, since ready_tasks only re-selects
    # pending/ready tasks). tick() still completes - weeding/dispatch/review
    # already ran.
    if integration_branch is not None and clean_ids:
        actual = current_branch_fn(repo)
        if actual != integration_branch:
            for tid in clean_ids:
                # Shares the merge-conflict escalation shape {task_id, error};
                # the retry-cap escalation site additionally carries `iterations`.
                result["escalations"].append({
                    "task_id": tid,
                    "error": (f"HEAD on {actual}, expected integration branch "
                              f"{integration_branch}"),
                })
            clean_ids = []  # skip all merges; claims remain held

    edges = [
        (tid, dep)
        for tid in clean_ids
        for dep in relations.neighbors(conn, tid, "depends-on", "out")
        if dep in clean_ids
    ]
    for tid in scheduler.merge_order(clean_ids, edges):
        try:
            merge_fn(repo, branches[tid])
        except Exception as e:  # noqa: BLE001 - merge conflict etc. -> escalate
            result["escalations"].append({"task_id": tid, "error": str(e)})
            continue  # leave claim held for retry / human intervention
        nodes.update_node(conn, tid, status="merged")
        claims.release_claim(conn, claim_ids[tid])
        # Any open dispatch-failure loop for a previously-flaky task was already
        # resolved at the CLEAN-verdict step (step 6), so nothing to do here.
        result["merged"].append(tid)

    # 8. Failed launches: route through _handle_failure, which records a
    # CriticalLoop strike. Strikes 1 and 2 reset the task to 'pending' and
    # release the claim so it re-enters the ready set next tick; the 3rd strike
    # escalates instead (status='escalated', no re-dispatch). An escalating
    # launch failure is recorded in BOTH result["failed"] (operational
    # visibility - the launch did fail this tick) and result["escalations"]
    # (its terminal state); this double-surfacing is intentional.
    for r in results:
        if not r.get("ok"):
            tid = r["task_id"]
            _handle_failure(conn, tid, claim_ids[tid],
                            r.get("error", "launch failed"), result)
            # Intentional double-surface: a launch failure that escalates lands
            # in both `failed` (this tick's failure) and `escalations` (terminal).
            result["failed"].append(tid)

    # 9. Return the tick summary.
    return result


# --- CLI -------------------------------------------------------------------
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # cp1252 default on this box
    parser = argparse.ArgumentParser(prog="agentic_mcp.orchestrate")
    parser.add_argument("--once", action="store_true",
                        help="run a single tick and exit")
    parser.add_argument("--pool", type=int, default=3,
                        help="max concurrent builder agents")
    parser.add_argument("--weed-days", type=int, default=14,
                        help="stale-spec threshold in days")
    parser.add_argument("--repo", default=".", help="repo root for git seams")
    parser.add_argument("--integration-branch", default=None,
                        help="if set, refuse to merge unless HEAD == this branch")
    args = parser.parse_args()

    conn = db.connect(db.resolve_db_path())
    try:
        result = tick(
            conn, repo=args.repo, pool_size=args.pool, weed_days=args.weed_days,
            integration_branch=args.integration_branch,
        )
    finally:
        conn.close()
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    main()

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
genuine programming errors propagate.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import calibration, claims, db, headless, nodes, relations, scheduler, weeding


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


def _real_worktree(repo: str, task_id: str) -> tuple[str, str]:
    branch = "orch/" + task_id
    path = str(Path(repo) / ".worktrees" / task_id)
    _git(["-C", repo, "worktree", "add", path, "-b", branch])
    return (path, branch)


def _real_merge(repo: str, branch: str) -> None:
    # check=True -> CalledProcessError on conflict, which tick() routes to
    # escalations (claim stays held so the next tick can retry / a human can act).
    _git(["-C", repo, "merge", "--no-ff", branch])


def _real_review(conn, task_id: str, job_result: dict) -> dict:
    """Minimal integration-default reviewer.

    Task 8's e2e overrides this with the real Phase-1 reviewer dispatch (spawn
    the code-reviewer agent, parse its verdict). Kept thin on purpose so this
    module composes cleanly without pulling in the review machinery.
    """
    return {"verdict": "CLEAN", "reviewer": "code-reviewer", "hit": True}


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
) -> dict:
    result = {
        "weeded": [],
        "dispatched": [],
        "merged": [],
        "failed": [],
        "escalations": [],
        "calibrated": [],
    }

    # 1. Weed stale specs.
    result["weeded"] = weeding.flag_stale_specs(conn, weed_days)

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
        wt, branch = worktree_factory(repo, tid)
        try:
            cid = claims.claim_scope(
                conn, tid, scope_paths, worktree=wt, branch=branch
            )
        except claims.ClaimConflict:
            # Another held claim overlaps (e.g. a task left in_progress from a
            # prior tick); skip - do not dispatch.
            continue
        nodes.update_node(conn, tid, status="in_progress")
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
        calibration.record_outcome(conn, reviewer, rv["hit"])
        adj = calibration.adjust_trust(conn, reviewer)
        if adj["adjusted"] and reviewer not in result["calibrated"]:
            result["calibrated"].append(reviewer)
        if rv["verdict"] == "CLEAN":
            clean_ids.append(tid)
        # NEEDS_FIXING: leave task in_progress, claim held, no merge - it loops
        # back into the ready/claimed set on a subsequent tick.

    # 7. Merge CLEAN tasks in dependency (topological) order.
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
        result["merged"].append(tid)

    # 8. Failed launches: task stays in_progress, claim stays held.
    for r in results:
        if not r.get("ok"):
            result["failed"].append(r["task_id"])

    # 9.
    return result


# --- CLI -------------------------------------------------------------------
def _db_path() -> Path:
    # Mirror server._db_path: resolve AGENTIC_DB_PATH (default ./.agentic/graph.db),
    # init if missing.
    raw = os.environ.get("AGENTIC_DB_PATH", "./.agentic/graph.db")
    p = Path(raw).resolve()
    if not p.exists():
        db.init_db(p)
    return p


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
    args = parser.parse_args()

    conn = db.connect(_db_path())
    try:
        result = tick(
            conn, repo=args.repo, pool_size=args.pool, weed_days=args.weed_days
        )
    finally:
        conn.close()
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    main()

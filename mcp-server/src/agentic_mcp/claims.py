"""Scope claims for serial-when-shared scheduling.

A claim records the repo-relative path globs a task will touch while a worker
holds a worktree. claim_scope refuses to record a held claim that overlaps an
existing held claim (so two parallel teams never touch the same surface).
detect_overlap is the pure batching helper the scheduler uses to pick the next
parallel set from a list of candidate task specs.

Claims are an auxiliary table, not a graph node type.
"""
from __future__ import annotations

import fnmatch
import json
import sqlite3
import uuid
from datetime import datetime, timezone


class ClaimConflict(RuntimeError):
    """Raised when a requested claim overlaps an already-held claim."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _paths_overlap(a: list[str], b: list[str]) -> bool:
    """True if any path/glob in *a* matches any in *b* (either direction)."""
    for pa in a:
        for pb in b:
            if pa == pb or fnmatch.fnmatch(pa, pb) or fnmatch.fnmatch(pb, pa):
                return True
    return False


def _held_claims(conn: sqlite3.Connection) -> list[list[str]]:
    return [
        json.loads(r[0])
        for r in conn.execute("SELECT scope_paths FROM claim WHERE status='held'")
    ]


def claim_scope(
    conn: sqlite3.Connection,
    task_id: str,
    scope_paths: list[str],
    worktree: str | None = None,
    branch: str | None = None,
) -> str:
    for held in _held_claims(conn):
        if _paths_overlap(scope_paths, held):
            raise ClaimConflict(
                f"task {task_id} scope {scope_paths} overlaps held claim {held}"
            )
    cid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO claim(id, task_id, scope_paths, worktree, branch, status, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (cid, task_id, json.dumps(scope_paths), worktree, branch, "held", _now()),
    )
    conn.commit()
    return cid


def release_claim(conn: sqlite3.Connection, claim_id: str) -> None:
    conn.execute("UPDATE claim SET status='released' WHERE id=?", (claim_id,))
    conn.commit()


def detect_overlap(candidates: list[dict]) -> list[dict]:
    """Greedy max-disjoint batch.

    *candidates* is a list of dicts each with a 'scope_paths' list. Returns the
    subset (in input order) whose path sets are mutually disjoint - the first
    candidate always wins, later ones join only if they overlap nothing already
    accepted.
    """
    accepted: list[dict] = []
    taken: list[str] = []
    for c in candidates:
        paths = c["scope_paths"]
        if not _paths_overlap(paths, taken):
            accepted.append(c)
            taken = taken + list(paths)
    return accepted

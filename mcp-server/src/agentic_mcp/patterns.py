"""Phase 3 sub-project A: the pattern-finder.

Bottom-up meta-review: cluster recurring Finding/Bug/Retro nodes into durable
Pattern nodes with a derived-from evidence trail. Built as a deliberate copy of
orchestrate.py's shape: a pure deterministic core (candidate_groups), an
injectable seam that is the only thing touching `claude` (confirm_fn, default
_real_confirm), and a never-raise single-tick driver (find_patterns_tick) safe to
run under cron/`/loop`. No new dependency, no schema migration; vec0 is a future
candidate source feeding the same candidate_groups interface.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import db, headless, nodes, relations

# Statuses that mean a Finding/Bug/Retro is no longer live evidence. Anything not
# in this set is eligible to group. Explicit so grouping stays deterministic.
_RESOLVED = ("resolved", "dismissed", "closed", "superseded", "done", "merged")


def _active_rows(conn, table: str, cols: list[str], scope) -> list[dict]:
    placeholders = ",".join("?" for _ in _RESOLVED)
    sql = f"SELECT {', '.join(cols)} FROM {table} WHERE status NOT IN ({placeholders})"
    params: list = list(_RESOLVED)
    if scope is not None:
        sql += " AND scope = ?"
        params.append(scope)
    return [dict(zip(cols, r)) for r in conn.execute(sql, params).fetchall()]


def _pattern_evidence_sets(conn) -> list[set[str]]:
    """For every existing Pattern (any status), the set of node ids it was minted
    derived-from. Used to dedup candidate groups so neither confirmed Patterns nor
    dismissed-tombstones re-trigger the confirm step on a later tick."""
    out: list[set[str]] = []
    for (pid,) in conn.execute("SELECT id FROM pattern").fetchall():
        ev = set(relations.neighbors(conn, pid, "derived-from", "out"))
        if ev:
            out.append(ev)
    return out


def candidate_groups(conn, scope=None, min_size: int = 3) -> list[dict]:
    """Pure. Group active Finding/Bug/Retro nodes by structural signal; drop
    groups smaller than min_size or already covered by an existing Pattern's
    evidence. Returns [{key, reason, evidence_ids}], deterministically ordered."""
    findings_ = _active_rows(conn, "finding",
                             ["id", "parent_id", "subtype", "tags"], scope)
    bugs = _active_rows(conn, "bug", ["id", "tags"], scope)
    retros = _active_rows(conn, "retro", ["id", "failed_layer", "tags"], scope)

    buckets: dict[str, set[str]] = {}

    def add(key: str, nid: str) -> None:
        buckets.setdefault(key, set()).add(nid)

    def add_tags(row: dict) -> None:
        raw = row.get("tags")
        if not raw:
            return
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return
        if isinstance(parsed, list):
            for t in parsed:
                add(f"tag:{t}", row["id"])

    for f in findings_:
        if f.get("parent_id"):
            add(f"parent:{f['parent_id']}", f["id"])
        if f.get("subtype"):
            add(f"subtype:{f['subtype']}", f["id"])
        add_tags(f)
    for b in bugs:
        add_tags(b)
    for r in retros:
        if r.get("failed_layer"):
            add(f"layer:{r['failed_layer']}", r["id"])
        add_tags(r)

    covered = _pattern_evidence_sets(conn)
    groups: list[dict] = []
    for key in sorted(buckets):
        ev = buckets[key]
        if len(ev) < min_size:
            continue
        if any(ev <= c for c in covered):
            continue
        kind, _, val = key.partition(":")
        reason = {
            "parent": f"{len(ev)} nodes share parent_id {val}",
            "subtype": f"{len(ev)} findings share subtype {val}",
            "tag": f"{len(ev)} nodes share tag/file {val}",
            "layer": f"{len(ev)} retros share failed_layer {val}",
        }.get(kind, f"{len(ev)} nodes share {key}")
        groups.append({"key": key, "reason": reason, "evidence_ids": sorted(ev)})
    return groups

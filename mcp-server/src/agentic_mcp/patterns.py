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


_TRIAGE = {"confirmed", "dismissed"}


def triage_pattern(conn, pattern_id: str, disposition: str) -> None:
    """Move a Pattern open -> confirmed | dismissed. Raises on misuse - this is a
    direct user/agent action (fail loud), unlike the never-raise tick."""
    if disposition not in _TRIAGE:
        raise ValueError(
            f"unknown disposition: {disposition!r}. Valid: {sorted(_TRIAGE)}")
    node = nodes.get_node(conn, pattern_id)
    if node is None or node["type"] != "Pattern":
        raise ValueError(f"not a Pattern: {pattern_id}")
    nodes.update_node(conn, pattern_id, status=disposition)


_PATTERN_AGENT = "pattern-finder"


def _default_source_root() -> str:
    # <repo>/mcp-server/src/agentic_mcp/patterns.py -> parents[3] == repo root,
    # which ships agents/ + commands/. Overridable via source_root (e.g. the e2e).
    return str(Path(__file__).resolve().parents[3])


def _stage_pattern_agent(source_root: str, repo: str) -> None:
    """Copy agents/pattern-finder.md into <repo>/.claude/agents/ so a headless
    `claude -p` run discovers it (headless has no slash commands but DOES discover
    project-level .claude/agents/*.md). Idempotent overwrite."""
    src = Path(source_root) / "agents" / f"{_PATTERN_AGENT}.md"
    dst = Path(repo) / ".claude" / "agents"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst / f"{_PATTERN_AGENT}.md")


def _confirm_prompt(conn, group: dict) -> str:
    lines = []
    for nid in group["evidence_ids"]:
        n = nodes.get_node(conn, nid)
        ntype = n["type"] if n else "?"
        body = (n["body"] if n else "").strip().replace("\n", " ")
        lines.append(f"- {nid} [{ntype}]: {body[:300]}")
    evidence = "\n".join(lines)
    ids_json = json.dumps(group["evidence_ids"])
    return (
        "You are the pattern-finder. Decide whether the evidence below is a\n"
        "GENUINE recurring pattern (a repeated root cause or theme) or just\n"
        "coincidence. Reject coincidence.\n\n"
        f"## Why these were grouped\n{group['reason']}\n\n"
        f"## Evidence nodes\n{evidence}\n\n"
        "## If and ONLY if this is a genuine recurring pattern\n"
        "1. Call the MCP tool create_node with type=\"Pattern\", status=\"open\",\n"
        "   owner=\"pattern-finder\", body=<one paragraph naming the pattern and\n"
        "   its hypothesis>, summary=<one line>.\n"
        "2. For EACH evidence id below, call link_nodes with from_id=<the new\n"
        "   Pattern id>, to_id=<evidence id>, relation_type=\"derived-from\":\n"
        f"   {ids_json}\n\n"
        "If it is NOT a genuine pattern, create no node. Stop when done.\n"
    )


def _real_confirm(conn, group: dict, *, repo, mcp_config, source_root) -> None:
    """Real confirm seam: stage the pattern-finder agent + run it headless with
    graph access so IT mints the Pattern. The tick derives the outcome from the
    graph (never parses prose). Only exercised by the llm-gated e2e; fast tests
    inject a stub confirm_fn."""
    _stage_pattern_agent(source_root, repo)
    headless.run_claude_headless(
        _confirm_prompt(conn, group), cwd=repo, mcp_config=mcp_config)


def _minted_for(conn, group: dict, before_ids: set) -> str | None:
    """A newly created open Pattern whose derived-from evidence covers this group."""
    ev = set(group["evidence_ids"])
    for (pid,) in conn.execute(
            "SELECT id FROM pattern WHERE status='open'").fetchall():
        if pid in before_ids:
            continue
        linked = set(relations.neighbors(conn, pid, "derived-from", "out"))
        if ev <= linked:
            return pid
    return None


def find_patterns_tick(conn, *, scope=None, db_path=None, confirm_fn=_real_confirm,
                       min_size: int = 3, repo: str = ".",
                       source_root: str | None = None) -> dict:
    """Never-raise single-tick driver. Serves /agentic:find-patterns (on demand)
    and cron/`/loop` (scheduled). Mirrors orchestrate.tick's never-raise contract:
    per-group failures land in result["errors"]; nothing propagates."""
    result = {"minted": [], "dismissed": [], "considered": 0, "errors": []}
    groups = candidate_groups(conn, scope=scope, min_size=min_size)
    result["considered"] = len(groups)
    if not groups:
        return result
    source_root = source_root or _default_source_root()
    mcp_config = None
    if db_path is not None:
        mcp_config = headless.stage_mcp_config(repo, db_path)
    for group in groups:
        try:
            before = {pid for (pid,) in conn.execute("SELECT id FROM pattern")}
            confirm_fn(conn, group, repo=repo, mcp_config=mcp_config,
                       source_root=source_root)
            # The agent committed any new Pattern via a SEPARATE process/connection.
            # Drop our connection's implicit transaction/snapshot so this read sees
            # those committed rows (cheap no-op when nothing is open).
            conn.commit()
            minted = _minted_for(conn, group, before)
            if minted:
                result["minted"].append(minted)
            else:
                tomb = nodes.create_node(
                    conn, "Pattern", status="dismissed", owner="system",
                    body=("pattern-finder: candidate group not confirmed as a real "
                          f"pattern. {group['reason']}. Tombstone to prevent "
                          "re-evaluation."),
                    summary="dismissed candidate (system tombstone)",
                    scope=scope,
                    tags=json.dumps(["pattern-finder", "tombstone"]),
                )
                for nid in group["evidence_ids"]:
                    relations.link_nodes(conn, tomb, nid, "derived-from")
                result["dismissed"].append(tomb)
        except Exception as e:  # noqa: BLE001 - never raise under cron; retry next tick
            result["errors"].append({"key": group["key"], "error": str(e)})
    return result


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # cp1252 default on this box
    parser = argparse.ArgumentParser(prog="agentic_mcp.patterns")
    parser.add_argument("--once", action="store_true",
                        help="run a single pattern-finding tick and exit")
    parser.add_argument("--scope", default=None,
                        help="restrict grouping to this scope")
    parser.add_argument("--repo", default=".",
                        help="repo root for agent staging + mcp config")
    parser.add_argument("--min-size", type=int, default=3,
                        help="min evidence nodes to form a candidate group")
    args = parser.parse_args()

    db_path = db.resolve_db_path()
    conn = db.connect(db_path)
    try:
        result = find_patterns_tick(
            conn, scope=args.scope, db_path=db_path, repo=args.repo,
            min_size=args.min_size,
        )
    finally:
        conn.close()
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

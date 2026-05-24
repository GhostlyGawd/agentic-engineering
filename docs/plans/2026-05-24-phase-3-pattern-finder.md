# Phase 3 Pattern-finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mine recurring `Finding`/`Bug`/`Retro` nodes into durable, triageable `Pattern` nodes with a `derived-from` evidence trail (Phase 3 sub-project A).

**Architecture:** A deliberate copy of `orchestrate.py`'s shape - a pure deterministic core (`candidate_groups`), an injectable seam that is the only thing touching `claude` (`confirm_fn`, default `_real_confirm`, which lets the agent mint Patterns via the graph so the tick derives results rather than parsing prose), and a never-raise single-tick driver (`find_patterns_tick`) safe under cron/`/loop`. Cleanly-rejected candidate groups get a system `dismissed`-tombstone Pattern so they don't re-trigger the LLM next tick.

**Tech Stack:** Python 3.12, SQLite (`agentic_mcp` package), the headless `claude` CLI wrapper (`headless.py`), pytest (`-m "not llm"` fast suite vs `-m llm` live gate). No new dependency, no schema migration.

**Spec:** `docs/superpowers/specs/2026-05-24-phase-3-pattern-finder-design.md` (approved 2026-05-24).

---

## Context an implementer must know first

- **Run pytest FROM `mcp-server/`** with the venv python: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`. The fast suite is currently `179 passed, 8 deselected`.
- **Module style:** `conn` is the first arg; `nodes.create_node`/`update_node`/`relations.link_nodes` each `conn.commit()` internally. `_now()` = `datetime.now(timezone.utc).isoformat(timespec="seconds")`.
- **`nodes.create_node(conn, type, **fields) -> id`**: `Pattern` requires only `status`, `owner`, `body` (base required). `status` is free-text (no CHECK on `pattern`), so `'open'`/`'confirmed'`/`'dismissed'` are all valid with NO migration. `Finding` additionally requires `severity` and `parent_id`.
- **`relations.link_nodes(conn, from_id, to_id, relation_type)`**: `'derived-from'` is valid. We always link **from the Pattern to each evidence node**, so `neighbors(conn, pattern_id, "derived-from", "out")` returns the evidence ids.
- **`relations.neighbors(conn, id, relation_type, direction)`** returns a `list[str]`.
- **`get_node(conn, id)`** returns a dict of that node's table columns, or `None`. `finding` has `parent_id`, `subtype`, `tags`; `bug` has `tags`; `retro` has `failed_layer`, `tags`. `tags` is a JSON array string or `NULL`.
- **Headless plumbing (reuse, do not reimplement):** `headless.run_claude_headless(prompt, cwd, timeout=900, mcp_config=None)` (prompt over stdin; `bypassPermissions`); `headless.stage_mcp_config(project, db_path) -> Path` (writes a resolved `.mcp.json` so a headless agent can reach the graph); `headless.claude_on_path() -> bool`.
- **The single-threaded freedom:** unlike `orchestrate.tick` (which dispatches builders in a thread Pool), `find_patterns_tick` runs the confirm step sequentially in its own thread, so `confirm_fn` MAY use `conn` directly. The agent it spawns writes to the same DB file via a SEPARATE MCP-server connection; after `run_claude_headless` returns, a fresh `SELECT` on the tick's `conn` sees those committed rows (same mechanism the review e2e relies on).
- **`tick()` never-raise contract:** `find_patterns_tick` runs unattended under cron/`/loop`; it MUST NOT raise. Per-group failures go into `result["errors"]`. By contrast `triage_pattern` is a direct user/agent action and SHOULD raise on misuse.
- **No non-ASCII** in any string literal you add (machine cp1252 gotcha). Plan text below is plain ASCII.

## File structure

| File | Responsibility | Change |
|------|----------------|--------|
| `mcp-server/src/agentic_mcp/patterns.py` | The whole sub-project: pure core + seam + driver + CLI | CREATE |
| `mcp-server/src/agentic_mcp/server.py` | Register the `triage_pattern` MCP tool | MODIFY |
| `mcp-server/tests/test_patterns.py` | Fast unit + driver composition tests | CREATE |
| `mcp-server/tests/test_server.py` | Bump tool-count assertion 25 -> 26; add triage_pattern roundtrip | MODIFY |
| `mcp-server/tests/test_agent_docs.py` | Structural guards for the new agent + command docs | MODIFY |
| `mcp-server/tests/test_patterns_e2e.py` | Live `llm`-marked closed-loop e2e | CREATE |
| `agents/pattern-finder.md` | Confirm-agent definition | CREATE |
| `commands/find-patterns.md` | On-demand command | CREATE |

---

### Task 1: `candidate_groups` pure helper + module skeleton

**Goal:** A pure function that groups active `Finding`/`Bug`/`Retro` nodes by structural signal, drops groups under `min_size` or already covered by an existing Pattern's evidence, and returns deterministic `{key, reason, evidence_ids}` dicts. No `claude`.

**Files:**
- Create: `mcp-server/src/agentic_mcp/patterns.py`
- Test: `mcp-server/tests/test_patterns.py`

**Acceptance Criteria:**
- [ ] Findings sharing a `parent_id` form a group when `>= min_size`.
- [ ] Findings sharing a `subtype`, nodes sharing a `tag`, and retros sharing a `failed_layer` each form groups.
- [ ] Groups with `< min_size` evidence are dropped.
- [ ] A group whose evidence set is a subset of an existing Pattern's `derived-from` evidence (ANY status, including `dismissed`) is dropped.
- [ ] `scope=None` selects all; a named `scope` selects only nodes with that exact scope.
- [ ] Malformed `tags` JSON on a node is skipped, not fatal.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k candidate_groups -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** in `mcp-server/tests/test_patterns.py`:

```python
"""Pattern-finder tests (Phase 3 sub-project A).

Fast suite: candidate_groups grouping/dedup, triage_pattern transitions, and
find_patterns_tick composition with a STUBBED confirm_fn (no real claude). The
live confirm seam is exercised only by test_patterns_e2e.py (llm-marked).
"""
import json

import pytest

from agentic_mcp import db, nodes, patterns, relations


def _mk_conn(tmp_db_path):
    db.init_db(tmp_db_path)
    return db.connect(tmp_db_path)


def _finding(conn, parent_id, *, subtype=None, tags=None, scope=None,
             severity="Suggested", status="open", body="f"):
    return nodes.create_node(
        conn, "Finding", status=status, owner="t", body=body, severity=severity,
        parent_id=parent_id, subtype=subtype, scope=scope,
        tags=json.dumps(tags) if tags is not None else None,
    )


def _retro(conn, failed_layer, *, scope=None, status="open"):
    return nodes.create_node(
        conn, "Retro", status=status, owner="t", body="r",
        failed_layer=failed_layer, scope=scope,
    )


def test_candidate_groups_groups_by_parent_id(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(3):
            _finding(conn, "S-1")
        groups = patterns.candidate_groups(conn, min_size=3)
        keys = {g["key"] for g in groups}
        assert "parent:S-1" in keys
        g = next(g for g in groups if g["key"] == "parent:S-1")
        assert len(g["evidence_ids"]) == 3
    finally:
        conn.close()


def test_candidate_groups_subtype_tag_and_layer(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(3):
            _finding(conn, "S-1", subtype="SystemUsabilityBug")
        for _ in range(3):
            _finding(conn, "S-2", tags=["src/x.py"])
        for _ in range(3):
            _retro(conn, "spec")
        keys = {g["key"] for g in patterns.candidate_groups(conn, min_size=3)}
        assert "subtype:SystemUsabilityBug" in keys
        assert "tag:src/x.py" in keys
        assert "layer:spec" in keys
    finally:
        conn.close()


def test_candidate_groups_min_size_floor(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        _finding(conn, "S-1")
        _finding(conn, "S-1")  # only 2 -> below default floor of 3
        assert patterns.candidate_groups(conn, min_size=3) == []
        assert any(g["key"] == "parent:S-1"
                   for g in patterns.candidate_groups(conn, min_size=2))
    finally:
        conn.close()


def test_candidate_groups_dedups_against_existing_pattern(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        ev = [_finding(conn, "S-1") for _ in range(3)]
        pat = nodes.create_node(conn, "Pattern", status="dismissed",
                                owner="system", body="tombstone")
        for nid in ev:
            relations.link_nodes(conn, pat, nid, "derived-from")
        # The only candidate group's evidence is fully covered -> dropped.
        assert patterns.candidate_groups(conn, min_size=3) == []
    finally:
        conn.close()


def test_candidate_groups_scope_filter(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        for _ in range(3):
            _finding(conn, "S-1", scope="alpha")
        assert patterns.candidate_groups(conn, scope="beta", min_size=3) == []
        assert patterns.candidate_groups(conn, scope="alpha", min_size=3)
    finally:
        conn.close()


def test_candidate_groups_tolerates_bad_tags(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        nodes.create_node(conn, "Bug", status="open", owner="t", body="b",
                          tags="{not json")
        for _ in range(3):
            _finding(conn, "S-9")
        # Bad tags on the bug must not raise; parent group still forms.
        keys = {g["key"] for g in patterns.candidate_groups(conn, min_size=3)}
        assert "parent:S-9" in keys
    finally:
        conn.close()
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k candidate_groups -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentic_mcp.patterns'`.

- [ ] **Step 3: Create `mcp-server/src/agentic_mcp/patterns.py`** with the module docstring, imports, and the pure core:

```python
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
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k candidate_groups -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/patterns.py mcp-server/tests/test_patterns.py
git commit -m "feat(patterns): candidate_groups pure helper (structural pre-cluster + dedup)"
```

---

### Task 2: `triage_pattern` helper

**Goal:** Move a Pattern `open -> confirmed | dismissed`, raising on misuse (unknown disposition or non-Pattern id). No `claude`.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/patterns.py` (append after `candidate_groups`)
- Test: `mcp-server/tests/test_patterns.py`

**Acceptance Criteria:**
- [ ] `triage_pattern(conn, pid, "confirmed")` sets the Pattern's status to `confirmed`.
- [ ] `triage_pattern(conn, pid, "dismissed")` sets it to `dismissed`.
- [ ] An unknown disposition raises `ValueError`.
- [ ] A non-Pattern id (or missing node) raises `ValueError`.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k triage_pattern -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** in `mcp-server/tests/test_patterns.py`:

```python
def test_triage_pattern_confirmed_and_dismissed(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        p1 = nodes.create_node(conn, "Pattern", status="open", owner="t", body="p")
        patterns.triage_pattern(conn, p1, "confirmed")
        assert nodes.get_node(conn, p1)["status"] == "confirmed"
        p2 = nodes.create_node(conn, "Pattern", status="open", owner="t", body="p")
        patterns.triage_pattern(conn, p2, "dismissed")
        assert nodes.get_node(conn, p2)["status"] == "dismissed"
    finally:
        conn.close()


def test_triage_pattern_rejects_bad_disposition(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        p = nodes.create_node(conn, "Pattern", status="open", owner="t", body="p")
        with pytest.raises(ValueError):
            patterns.triage_pattern(conn, p, "maybe")
    finally:
        conn.close()


def test_triage_pattern_rejects_non_pattern(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        bug = nodes.create_node(conn, "Bug", status="open", owner="t", body="b")
        with pytest.raises(ValueError):
            patterns.triage_pattern(conn, bug, "confirmed")
        with pytest.raises(ValueError):
            patterns.triage_pattern(conn, "no-such-id", "confirmed")
    finally:
        conn.close()
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k triage_pattern -v`
Expected: FAIL with `AttributeError: module 'agentic_mcp.patterns' has no attribute 'triage_pattern'`.

- [ ] **Step 3: Implement** in `mcp-server/src/agentic_mcp/patterns.py` (after `candidate_groups`):

```python
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
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k triage_pattern -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/patterns.py mcp-server/tests/test_patterns.py
git commit -m "feat(patterns): triage_pattern (open -> confirmed/dismissed)"
```

---

### Task 3: `find_patterns_tick` driver + `_real_confirm` seam

**Goal:** The never-raise single-tick driver. For each candidate group it runs `confirm_fn` (default `_real_confirm`, which stages the pattern-finder agent and runs it headless so the agent mints the Pattern via the graph), derives whether a Pattern was minted, and otherwise writes a system `dismissed`-tombstone. A `confirm_fn` that raises records an error and does NOT tombstone (retried next tick).

**Files:**
- Modify: `mcp-server/src/agentic_mcp/patterns.py` (append the seam helpers + driver)
- Test: `mcp-server/tests/test_patterns.py`

**Acceptance Criteria:**
- [ ] When `confirm_fn` mints an `open` Pattern linked `derived-from` the group's evidence, the tick records its id in `result["minted"]`.
- [ ] When `confirm_fn` returns cleanly but mints nothing, the tick creates a `dismissed`/`owner='system'` Pattern linked `derived-from` the evidence and records it in `result["dismissed"]`.
- [ ] When `confirm_fn` raises, the tick records `{"key", "error"}` in `result["errors"]` and mints NO Pattern (no tombstone) for that group.
- [ ] `result["considered"]` equals the number of candidate groups.
- [ ] No `.mcp.json` is staged when `db_path is None`, and none when there are no candidate groups.
- [ ] When `db_path` is set AND there is at least one group, `headless.stage_mcp_config(repo, db_path)` is called once and the staged path is passed to `confirm_fn` as `mcp_config`.
- [ ] The tick never raises (a raising `confirm_fn` is folded into `errors`).

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k tick -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** in `mcp-server/tests/test_patterns.py`:

```python
# --- find_patterns_tick (confirm_fn stubbed; no real claude) --------------
def _three_findings(conn, parent="S-1"):
    return [_finding(conn, parent) for _ in range(3)]


def test_tick_records_minted_when_agent_mints(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        ev = _three_findings(conn)

        def stub_confirm(conn_, group, *, repo, mcp_config, source_root):
            pid = nodes.create_node(conn_, "Pattern", status="open",
                                    owner="pattern-finder", body="real pattern")
            for nid in group["evidence_ids"]:
                relations.link_nodes(conn_, pid, nid, "derived-from")

        result = patterns.find_patterns_tick(
            conn, confirm_fn=stub_confirm, repo=".", db_path=None)
        assert result["considered"] == 1
        assert len(result["minted"]) == 1
        assert result["dismissed"] == []
        minted = nodes.get_node(conn, result["minted"][0])
        assert minted["status"] == "open"
        linked = set(relations.neighbors(conn, result["minted"][0],
                                         "derived-from", "out"))
        assert set(ev) <= linked
    finally:
        conn.close()


def test_tick_tombstones_when_agent_declines(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        ev = _three_findings(conn)

        def stub_decline(conn_, group, *, repo, mcp_config, source_root):
            return None  # agent ran, judged "not a pattern", minted nothing

        result = patterns.find_patterns_tick(
            conn, confirm_fn=stub_decline, repo=".", db_path=None)
        assert result["minted"] == []
        assert len(result["dismissed"]) == 1
        tomb = nodes.get_node(conn, result["dismissed"][0])
        assert tomb["status"] == "dismissed"
        assert tomb["owner"] == "system"
        linked = set(relations.neighbors(conn, tomb["id"], "derived-from", "out"))
        assert set(ev) <= linked
    finally:
        conn.close()


def test_tick_never_raises_on_confirm_error(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        _three_findings(conn)

        def boom(conn_, group, *, repo, mcp_config, source_root):
            raise RuntimeError("agent exploded")

        result = patterns.find_patterns_tick(
            conn, confirm_fn=boom, repo=".", db_path=None)
        assert result["minted"] == []
        assert result["dismissed"] == []
        assert len(result["errors"]) == 1
        assert "agent exploded" in result["errors"][0]["error"]
        # No tombstone -> the group is retried next tick.
        assert conn.execute("SELECT COUNT(*) FROM pattern").fetchone()[0] == 0
    finally:
        conn.close()


def test_tick_no_groups_no_staging(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        result = patterns.find_patterns_tick(
            conn, confirm_fn=lambda *a, **k: None,
            repo=str(repo), db_path=db_path)
        assert result["considered"] == 0
        assert not (repo / ".mcp.json").exists()
    finally:
        conn.close()


def test_tick_stages_mcp_config_when_db_path_set(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        _three_findings(conn)
        seen = {}

        def capture(conn_, group, *, repo, mcp_config, source_root):
            seen["mcp_config"] = mcp_config  # mint nothing

        patterns.find_patterns_tick(
            conn, confirm_fn=capture, repo=str(repo), db_path=db_path)
        assert (repo / ".mcp.json").exists()
        assert seen["mcp_config"] == repo / ".mcp.json"
    finally:
        conn.close()
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k tick -v`
Expected: FAIL with `AttributeError: module 'agentic_mcp.patterns' has no attribute 'find_patterns_tick'`.

- [ ] **Step 3: Implement** in `mcp-server/src/agentic_mcp/patterns.py` (after `triage_pattern`). `_real_confirm` MUST be defined BEFORE `find_patterns_tick` because it is the default-arg value:

```python
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


def _minted_for(conn, group: dict, before_ids: set[str]) -> str | None:
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
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k tick -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/patterns.py mcp-server/tests/test_patterns.py
git commit -m "feat(patterns): find_patterns_tick driver + _real_confirm seam (graph-minted, tombstone idempotency)"
```

---

### Task 4: `main()` CLI

**Goal:** A `--once`-style CLI that resolves the DB path, runs one `find_patterns_tick`, and prints the result dict as JSON. Modeled on `orchestrate.main()`.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/patterns.py` (append `main` + `__main__` guard)
- Test: `mcp-server/tests/test_patterns.py`

**Acceptance Criteria:**
- [ ] `patterns.main()` parses `--once`, `--scope`, `--repo`, `--min-size`.
- [ ] It resolves the DB via `db.resolve_db_path()`, runs a tick, and prints valid JSON containing the `minted`/`dismissed`/`considered`/`errors` keys.
- [ ] On an empty graph it prints `considered: 0` and exits 0 with no `.mcp.json` side effect.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k cli -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing test** in `mcp-server/tests/test_patterns.py`:

```python
def test_cli_main_prints_json(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    monkeypatch.setattr(patterns.db, "resolve_db_path", lambda: db_path)
    monkeypatch.setattr(sys, "argv", ["patterns", "--once", "--repo", str(tmp_path)])
    import sys  # noqa: F401 - referenced via monkeypatch above
    rc = patterns.main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["considered"] == 0
    assert set(out) >= {"minted", "dismissed", "considered", "errors"}
    assert not (tmp_path / ".mcp.json").exists()
```

Note: add `import sys` to the test file's top-of-module imports (it is used by the monkeypatch). Remove the inline `import sys` line above if your linter flags it; it is shown only to make the dependency explicit.

- [ ] **Step 2: Run the test, verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k cli -v`
Expected: FAIL with `AttributeError: module 'agentic_mcp.patterns' has no attribute 'main'`.

- [ ] **Step 3: Implement** in `mcp-server/src/agentic_mcp/patterns.py` (end of file):

```python
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
```

- [ ] **Step 4: Run the test, then the FULL fast suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns.py -k cli -v`
Expected: 1 passed.

Run: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: previous 179 + the new `test_patterns.py` tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/patterns.py mcp-server/tests/test_patterns.py
git commit -m "feat(patterns): --once CLI (resolve db, run tick, print json)"
```

---

### Task 5: Register the `triage_pattern` MCP tool

**Goal:** Expose `patterns.triage_pattern` as an MCP tool so an agent or `/agentic:find-patterns` can record a Pattern's disposition through the graph server.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/server.py` (import + Tool entry + dispatch branch)
- Test: `mcp-server/tests/test_server.py` (bump count 25 -> 26; add a roundtrip)

**Acceptance Criteria:**
- [ ] `list_tools()` includes `triage_pattern` and the total count assertion is updated to 26.
- [ ] `call_tool("triage_pattern", {"pattern_id", "disposition"})` sets the Pattern's status and returns `{"ok": True}`.
- [ ] A bad disposition / non-Pattern id returns an `error` payload (the existing `call_tool` try/except maps the `ValueError` to `_err`).

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_server.py -v` -> all pass

**Steps:**

- [ ] **Step 1: Update/add the failing tests** in `mcp-server/tests/test_server.py`. Change the count in `test_phase2_tools_listed` from `25` to `26`, add `triage_pattern` to the membership set, and add a roundtrip test:

```python
def test_phase2_tools_listed():
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools.tools} if hasattr(tools, "tools") else {t.name for t in tools}
    assert {"claim_scope", "release_claim", "detect_overlap", "flag_stale",
            "record_outcome", "get_calibration", "adjust_trust",
            "triage_pattern"} <= names
    assert len(names) == 26


def test_triage_pattern_tool_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    created = asyncio.run(server.call_tool(
        "create_node", {"type": "Pattern", "status": "open", "owner": "t", "body": "p"}))
    pid = json.loads(created[0].text)["id"]
    out = asyncio.run(server.call_tool(
        "triage_pattern", {"pattern_id": pid, "disposition": "confirmed"}))
    assert json.loads(out[0].text) == {"ok": True}
    got = asyncio.run(server.call_tool("get_node", {"id": pid}))
    assert json.loads(got[0].text)["status"] == "confirmed"


def test_triage_pattern_tool_bad_disposition_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_path / "graph.db"))
    created = asyncio.run(server.call_tool(
        "create_node", {"type": "Pattern", "status": "open", "owner": "t", "body": "p"}))
    pid = json.loads(created[0].text)["id"]
    out = asyncio.run(server.call_tool(
        "triage_pattern", {"pattern_id": pid, "disposition": "nope"}))
    assert "error" in json.loads(out[0].text)
```

Note: `test_phase2_tools_listed` originally read `{t.name for t in tools}`. Keep whichever form matches the current file - the only required change there is the count `25 -> 26` and adding `triage_pattern` to the membership assertion. The two helper lines above are written defensively; match the existing style.

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_server.py -k "tools_listed or triage_pattern" -v`
Expected: FAIL - count is 25 (not 26) and `triage_pattern` is unknown (`call_tool` returns an `error` for an unknown tool name).

- [ ] **Step 3: Implement** in `mcp-server/src/agentic_mcp/server.py`:

Add the import near the other module imports (after line 25, `from . import calibration as calib_mod`):

```python
from . import patterns as patterns_mod
```

Add the Tool entry inside `list_tools()` (after the `record_triage` Tool block, before `log_retro`):

```python
        Tool(
            name="triage_pattern",
            description="Triage a Pattern: set status to 'confirmed' or 'dismissed'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern_id": {"type": "string"},
                    "disposition": {"type": "string"},
                },
                "required": ["pattern_id", "disposition"],
            },
        ),
```

Add the dispatch branch inside `call_tool()` (after the `record_triage` branch):

```python
        if name == "triage_pattern":
            patterns_mod.triage_pattern(
                conn, arguments["pattern_id"], arguments["disposition"])
            return _ok({"ok": True})
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_server.py -v`
Expected: all pass (count now 26).

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/server.py mcp-server/tests/test_server.py
git commit -m "feat(server): register triage_pattern MCP tool"
```

---

### Task 6: `pattern-finder` agent + `find-patterns` command docs

**Goal:** Ship `agents/pattern-finder.md` (the confirm agent the live seam stages) and `commands/find-patterns.md` (the on-demand surface), with structural doc-guards.

**Files:**
- Create: `agents/pattern-finder.md`
- Create: `commands/find-patterns.md`
- Test: `mcp-server/tests/test_agent_docs.py` (append two tests)

**Acceptance Criteria:**
- [ ] `agents/pattern-finder.md` has valid frontmatter (`name: pattern-finder`, `model: sonnet`), instructs the agent to mint via `create_node` + `link_nodes` with `derived-from`, and to reject coincidence.
- [ ] `commands/find-patterns.md` has an `argument-hint`, references `query_graph` (to list open Patterns) and `triage_pattern`.
- [ ] Both doc tests pass; the full fast suite is green.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_agent_docs.py -k "pattern_finder or find_patterns" -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing doc tests** in `mcp-server/tests/test_agent_docs.py` (append):

```python
def test_pattern_finder_doc():
    t = _doc("agents/pattern-finder.md")
    assert "name: pattern-finder" in t
    assert "model: sonnet" in t
    assert "create_node" in t and "link_nodes" in t
    assert "derived-from" in t
    low = t.lower()
    assert "coincidence" in low
    assert "genuine" in low or "recurring" in low


def test_find_patterns_command_doc():
    t = _doc("commands/find-patterns.md")
    low = t.lower()
    assert "argument-hint" in low
    assert "pattern" in low
    assert "query_graph" in t
    assert "triage_pattern" in t
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_agent_docs.py -k "pattern_finder or find_patterns" -v`
Expected: FAIL - the doc files do not exist (`_doc` raises `FileNotFoundError`).

- [ ] **Step 3: Create `agents/pattern-finder.md`** (ASCII only):

```markdown
---
name: pattern-finder
description: Judges whether a structurally-grouped set of Finding/Bug/Retro nodes is a GENUINE recurring pattern, and if so mints a Pattern node linked derived-from its evidence. Phase 3 (meta-review, bottom-up). Rejects coincidence.
model: sonnet
---

You are the pattern-finder for the Agentic Engineering System.

## What you do

You receive a candidate group: several Finding/Bug/Retro nodes that share a
structural signal (same parent, same subtype, same tag/file, or same failed
layer), plus the reason they were grouped. Your job is the judgment the
deterministic pre-cluster cannot make: is this a GENUINE recurring pattern - a
single repeated root cause or theme worth tracking - or just coincidence?

Be conservative. Shared structure is necessary, not sufficient. Three findings on
one spec might be three unrelated nits, or they might be one recurring blind spot.
Only the latter is a pattern. Reject coincidence; minting noise is worse than
missing a weak signal (the same group will resurface if it recurs).

## If and only if it is a genuine recurring pattern

1. Call `create_node` with `type="Pattern"`, `status="open"`,
   `owner="pattern-finder"`, a `body` of one paragraph naming the pattern and its
   hypothesis (what recurs, the likely root cause), and a one-line `summary`.
2. For EVERY evidence id you were given, call `link_nodes` with
   `from_id=<the new Pattern id>`, `to_id=<evidence id>`,
   `relation_type="derived-from"`. Link them ALL - the evidence trail is the point.

If it is not a genuine pattern, create no node and stop. The orchestrator records
a system tombstone for declined groups; you do not need to.

## You do not

- You do not triage Patterns (open -> confirmed/dismissed). That is a human or
  architectural-review decision.
- You do not act on patterns (spawn ArchDebt/Spec, edit prompts). Out of scope.
```

- [ ] **Step 4: Create `commands/find-patterns.md`** (ASCII only):

```markdown
---
description: Surface recurring patterns in the graph. Lists open Pattern nodes awaiting triage, then runs one pattern-finding tick over the Finding/Bug/Retro stream (structural pre-cluster -> pattern-finder confirm -> mint with a derived-from evidence trail). On-demand companion to the scheduled tick.
argument-hint: "[scope]"
---

You are surfacing recurring patterns. Pattern STATE lives in the graph; this
command drives one pass and reports.

## Step 1 - Show open patterns awaiting triage

Call `query_graph(type="Pattern", status="open")`. For each, print its id,
summary, and the count of its `derived-from` evidence. These are candidates a
human (or the architectural-review layer) should triage with `triage_pattern`
(disposition `confirmed` or `dismissed`).

## Step 2 - Run one pattern-finding tick

Run the single-tick finder over the current graph (optionally scoped to `$1`):

```
python -m agentic_mcp.patterns --once --scope $1
```

It groups active Finding/Bug/Retro nodes by structural signal (shared parent_id,
subtype, tag/file, or failed_layer), and for each group of >= 3 it asks the
pattern-finder agent to confirm or reject. Confirmed groups become open Pattern
nodes (linked `derived-from` their evidence); declined groups get a system
dismissed-tombstone so they are not re-evaluated next run.

## Step 3 - Report

Print the tick's JSON summary (`minted`, `dismissed`, `considered`, `errors`).
Newly `minted` Patterns are `open` - surface them for triage via `triage_pattern`.
```

- [ ] **Step 5: Run the doc tests, then the FULL fast suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_agent_docs.py -k "pattern_finder or find_patterns" -v`
Expected: 2 passed.

Run: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: all green (179 + new `test_patterns.py` + `test_server.py` additions + these 2).

- [ ] **Step 6: Commit**

```bash
git add agents/pattern-finder.md commands/find-patterns.md mcp-server/tests/test_agent_docs.py
git commit -m "feat(agents): pattern-finder agent + find-patterns command"
```

---

### Task 7: Live `llm`-marked end-to-end (3 findings -> confirmed Pattern)

**Goal:** An on-demand `llm`-marked e2e proving the closed loop with the REAL `_real_confirm` seam: 3 related findings -> the staged pattern-finder agent mints one `open` Pattern linked `derived-from` all evidence -> `triage_pattern` moves it to `confirmed`.

**Files:**
- Create: `mcp-server/tests/test_patterns_e2e.py`

**Acceptance Criteria:**
- [ ] Marked `pytest.mark.llm` and `skipif(not headless.claude_on_path())` - excluded from the fast suite, skips when `claude` is absent.
- [ ] Uses the REAL `_real_confirm` (only `db_path`, `repo`, and `source_root` are supplied; no confirm stub).
- [ ] After the tick: exactly one entry in `result["minted"]`, the Pattern's status is `open`, and it is linked `derived-from` all three evidence findings.
- [ ] `triage_pattern(conn, pid, "confirmed")` then reports the Pattern status as `confirmed`.
- [ ] Structured graph assertions only - no prose/stdout inspection.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_patterns_e2e.py -m llm -v` (requires `claude` on PATH; one real `claude -p` session).

**Steps:**

- [ ] **Step 1: Write the e2e** at `mcp-server/tests/test_patterns_e2e.py`:

```python
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
```

- [ ] **Step 2: Confirm it is excluded from the fast suite**

Run: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: the new e2e is among the deselected (deselected count rises); fast suite still 0 failures.

- [ ] **Step 3: Run the live e2e** (requires `claude` on PATH; long-running)

Run: `./.venv/Scripts/python.exe -m pytest tests/test_patterns_e2e.py -m llm -v`
Expected: 1 passed. If `claude` is not on PATH: 1 skipped.

If it fails, debug against ACTUAL graph state (read the `pattern` rows and their `derived-from` neighbors), NOT the claude prose - per the repo's "verify the graph, don't trust reports" lesson. If the agent minted the Pattern but missed a `derived-from` link, that is a real prompt weakness in `agents/pattern-finder.md` (tighten the "link them ALL" instruction); do not weaken the assertion.

- [ ] **Step 4: Commit**

```bash
git add mcp-server/tests/test_patterns_e2e.py
git commit -m "test(e2e): live pattern-finder closed loop (3 findings -> confirmed Pattern, llm-marked)"
```

---

## Deferred / out of scope (from the spec, recorded so it is not silently dropped)

- **vec0 / sqlite-vec vector candidate source** - future enhancement; plugs into the `candidate_groups` interface as another bucket source. Not built here.
- **Cross-scope correlation + cross-project meta-graph** - sub-project C.
- **Acting on confirmed Patterns** (spawn ArchDebt/Spec, edit prompts/thresholds) - sub-project B / Phase 4.
- **Fuzzy overlap-threshold dedup** - default is full-coverage subset dedup; a partial-overlap threshold is a later refinement if churn is observed.
- **Repair/relitigation of grouping signals** - the four signals (parent_id, subtype, tag/file, failed_layer) are the agreed starting set.

## Self-review (run against the spec)

- **Spec coverage:** Component 1 `candidate_groups` (Task 1); Pattern lifecycle + `triage_pattern` (Task 2, MCP-exposed in Task 5); `find_patterns_tick` driver + `_real_confirm` graph-minting seam + dismissed-tombstone idempotency + never-raise (Task 3); single-tick CLI serving on-demand + cron (Task 4); `pattern-finder` agent + `/find-patterns` command (Task 6); `llm`-marked closed-loop e2e (Task 7). Within-scope-only, hybrid-detection, 3-occurrence bar, derive-from-graph, no-migration/no-dependency all honored.
- **Type consistency:** `confirm_fn(conn, group, *, repo, mcp_config, source_root) -> None` is the single seam signature used by `_real_confirm`, the tick call site, and every stub in tests. `candidate_groups(...) -> list[{key, reason, evidence_ids}]` is consumed identically by the tick and `_minted_for`. `triage_pattern(conn, pattern_id, disposition)` matches between the helper, the MCP tool, and the e2e. Pattern links are always `from_id=Pattern, to_id=evidence, "derived-from"`, so every `neighbors(pid, "derived-from", "out")` read is correct.
- **Placeholder scan:** every code step shows complete code; no TBD/TODO; exact verify commands with expected output.

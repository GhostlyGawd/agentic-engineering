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


def test_candidate_groups_superset_not_covered(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        ev = [_finding(conn, "S-1") for _ in range(3)]
        # A Pattern covering only 2 of the 3 does NOT cover the 3-node group
        # (the group is a strict superset of the Pattern's evidence), so the
        # group must STILL be returned. This distinguishes the correct subset
        # check (ev <= covered) from a buggy superset/equality check.
        pat = nodes.create_node(conn, "Pattern", status="open", owner="system",
                                body="partial")
        for nid in ev[:2]:
            relations.link_nodes(conn, pat, nid, "derived-from")
        keys = {g["key"] for g in patterns.candidate_groups(conn, min_size=3)}
        assert "parent:S-1" in keys
    finally:
        conn.close()


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


def test_cli_main_prints_json(tmp_db_path, monkeypatch, capsys):
    db.init_db(tmp_db_path)  # empty graph
    monkeypatch.setenv("AGENTIC_DB_PATH", str(tmp_db_path))
    monkeypatch.setattr("sys.argv",
                        ["patterns", "--once", "--repo", str(tmp_db_path.parent)])
    rc = patterns.main()
    out = json.loads(capsys.readouterr().out)
    assert out["considered"] == 0
    assert set(out) >= {"minted", "dismissed", "considered", "errors"}
    assert rc in (0, None)
    assert not (tmp_db_path.parent / ".mcp.json").exists()

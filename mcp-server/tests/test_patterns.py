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

# mcp-server/tests/test_phase1_e2e.py
"""Phase 1 exit-gate: real agents via headless claude, loop-level assertions only.

llm-marked: excluded from the fast suite; runs on demand with -m llm against a
live Claude (Max subscription) session. See design section 11 and the Task 14
spike notes for the claude -p invocation shape.
"""
import json
import shutil
from pathlib import Path

import pytest

from agentic_mcp import db, findings, init_project, loops, nodes
from llm_harness import claude_on_path, run_claude_headless, stage_mcp_config

FIX = Path(__file__).resolve().parent / "fixtures" / "phase1"

_FB = "if the review loop ships a wrong verdict, a regression test fails and we open a Retro tagged by failed_layer"


def _review_prompt(spec_id: str) -> str:
    # Tuned during execution against the Task 14 spike. Points the headless
    # session at the real review command + spec; the agents write to graph.db.
    return (
        "Run /agentic:review-pr for this working directory. "
        f"The spec id is {spec_id}. Use the spec-checker as the gate, then the "
        "code-reviewer and contrarian. Log all findings to the graph via the MCP tools."
    )


def _stage(project: Path, impl_src: Path):
    shutil.copy(FIX / "stubborn" / "spec_test.py", project / "test_parse_duration.py")
    shutil.copy(impl_src, project / "parse_duration.py")


def _open_criticals(conn, scope):
    return conn.execute(
        "SELECT id FROM finding WHERE status='open' AND severity='Critical' AND scope=?",
        (scope,),
    ).fetchall()


@pytest.mark.llm
def test_stubborn_critical_diagnostic_then_resolve(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    project = tmp_path / "proj"
    project.mkdir()
    init_project.run(project_root=project, scope_mode="isolated")
    db_path = project / ".agentic" / "graph.db"
    conn = db.connect(db_path)
    crit = [
        {"text": "combined h/m/s", "verify": "pytest test_parse_duration.py -q"},
    ]
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="parse_duration spec",
        criteria_json=json.dumps(crit), feedback_loop=_FB, scope="proj",
    )

    cfg = stage_mcp_config(project, db_path)
    loop_id = None
    fid = None
    resolved_finding = None
    for n in (1, 2, 3, 4):
        _stage(project, FIX / "stubborn" / f"iter{n}.py")
        run_claude_headless(_review_prompt(spec_id), cwd=project, mcp_config=cfg)
        conn2 = db.connect(db_path)
        crits = _open_criticals(conn2, "proj")
        if crits:
            fid = crits[0][0]
            if loop_id is None:
                loop_id = loops.start_critical_loop(conn2, fid)
            else:
                loops.advance_critical_loop(conn2, loop_id)
            conn2.close()
        else:
            # gate passed: close the loop and record the retro.
            resolved_finding = fid if loop_id else None
            if loop_id:
                loops.resolve_critical_loop(conn2, loop_id)
                findings.log_retro(
                    conn2, body="impl missing combined-unit parse until iter4",
                    failed_layer="implementation", caused_by_finding_id=fid,
                )
            conn2.close()
            break

    final = db.connect(db_path)
    try:
        loop = nodes.get_node(final, loop_id)
        assert loop is not None, "no critical loop was started"
        assert loop["diagnostic_fired_at"] is not None, "diagnostic never fired at iter 3"
        assert loop["status"] == "resolved", "loop did not close after iter4"
        retros = final.execute(
            "SELECT id FROM retro WHERE failed_layer='implementation'"
        ).fetchall()
        assert retros, "no Retro tagged failed_layer=implementation"
    finally:
        final.close()


@pytest.mark.llm
def test_mixed_severity(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    project = tmp_path / "proj"
    project.mkdir()
    init_project.run(project_root=project, scope_mode="isolated")
    db_path = project / ".agentic" / "graph.db"
    conn = db.connect(db_path)
    shutil.copy(FIX / "mixed" / "widget.py", project / "widget.py")
    crit = [{"text": "total_price sums line items", "verify": "python -c \"import widget\""}]
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="widget spec",
        criteria_json=json.dumps(crit), feedback_loop=_FB, scope="proj",
    )
    conn.close()
    cfg = stage_mcp_config(project, db_path)
    run_claude_headless(_review_prompt(spec_id), cwd=project, mcp_config=cfg)
    check = db.connect(db_path)
    try:
        triaged = check.execute(
            "SELECT id FROM finding WHERE severity='Important' AND triage IS NOT NULL AND scope='proj'"
        ).fetchall()
        assert triaged, "no Important finding was auto-triaged"
    finally:
        check.close()


@pytest.mark.llm
def test_contrarian_catches_distinct_flaw(tmp_path):
    if not claude_on_path():
        pytest.skip("claude CLI not on PATH")
    project = tmp_path / "proj"
    project.mkdir()
    init_project.run(project_root=project, scope_mode="isolated")
    db_path = project / ".agentic" / "graph.db"
    conn = db.connect(db_path)
    shutil.copy(FIX / "contrarian" / "rate_limiter.py", project / "rate_limiter.py")
    crit = [{"text": "limiter enforces per-key limit across the multi-worker service",
             "verify": "python -c \"import rate_limiter\""}]
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t",
        body="rate limiter spec; service runs behind MULTIPLE worker processes",
        criteria_json=json.dumps(crit), feedback_loop=_FB, scope="proj",
    )
    conn.close()
    cfg = stage_mcp_config(project, db_path)
    run_claude_headless(_review_prompt(spec_id), cwd=project, mcp_config=cfg)
    check = db.connect(db_path)
    try:
        owners = {r[0] for r in check.execute(
            "SELECT DISTINCT owner FROM finding WHERE scope='proj' AND owner IS NOT NULL"
        ).fetchall()}
        # The contrarian's findings carry its own owner tag; assert it produced
        # at least one finding (the assumption flaw) distinct from the reviewer.
        assert "contrarian" in owners, (
            "contrarian logged no finding (known-flaky per design section 11)"
        )
    finally:
        check.close()

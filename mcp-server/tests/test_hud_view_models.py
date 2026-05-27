import json

import pytest

from agentic_mcp import db, nodes, relations
from agentic_mcp.hud import view_models as vm


@pytest.fixture
def conn(tmp_path):
    p = tmp_path / "graph.db"
    db.init_db(p)
    c = db.connect(p)
    yield c
    c.close()


def _goal_epic_task(c):
    goal = nodes.create_node(c, "Goal", status="open", owner="t", body="Goal A")
    epic = nodes.create_node(c, "Epic", status="open", owner="t", body="Epic A")
    task = nodes.create_node(c, "Task", status="pending", owner="t", body="Task A")
    relations.link_nodes(c, epic, goal, "implements")
    relations.link_nodes(c, task, epic, "implements")
    return goal, epic, task


def test_board_view_builds_levels_and_tree(conn):
    goal, epic, task = _goal_epic_task(conn)
    model = vm.board_view(conn)
    assert [g.node["id"] for g in model.goals] == [goal]
    assert model.goals[0].children[0].node["id"] == epic
    assert model.goals[0].children[0].children[0].node["id"] == task
    assert {n["id"] for n in model.by_level["Task"]} == {task}


def test_signals_view_empty_is_not_an_error(conn):
    model = vm.signals_view(conn)
    assert model.patterns == []
    assert model.arch_debt == []
    assert model.calibration == []


def test_signals_view_collects_patterns_and_distrusted_calibration(conn):
    nodes.create_node(conn, "Pattern", status="confirmed", owner="t", body="P1")
    conn.execute("INSERT INTO calibration(role, score, distrusted, observations, hits, misses)"
                 " VALUES ('code-reviewer', 0.30, 1, 10, 3, 7)")
    conn.commit()
    model = vm.signals_view(conn)
    assert len(model.patterns) == 1
    assert model.calibration[0]["role"] == "code-reviewer"
    assert model.calibration[0]["distrusted"] == 1


def test_task_sheet_view_assembles_sheet(conn):
    goal, epic, task = _goal_epic_task(conn)
    sig = nodes.create_node(conn, "Pattern", status="confirmed", owner="t", body="why")
    spec = nodes.create_node(conn, "Spec", status="draft", owner="t", body="spec body",
                             criteria_json=json.dumps(["crit-1", "crit-2"]),
                             feedback_loop="run tests")
    review = nodes.create_node(conn, "Review", status="done", owner="t", body="LGTM",
                               verdict="CLEAN")
    relations.link_nodes(conn, task, sig, "derived-from")
    relations.link_nodes(conn, spec, task, "implements")
    relations.link_nodes(conn, review, task, "references")
    sheet = vm.task_sheet_view(conn, task)
    assert sheet.task["id"] == task
    assert sheet.criteria == ["crit-1", "crit-2"]
    assert sheet.origin_signal["id"] == sig
    assert sheet.parent["id"] == epic
    assert [r["id"] for r in sheet.reviews] == [review]


def test_task_sheet_view_missing_spec_and_links(conn):
    task = nodes.create_node(conn, "Task", status="pending", owner="t", body="lonely")
    sheet = vm.task_sheet_view(conn, task)
    assert sheet.spec is None
    assert sheet.criteria == []
    assert sheet.origin_signal is None
    assert sheet.parent is None
    assert sheet.reviews == []


def test_overview_counts(conn):
    nodes.create_node(conn, "Task", status="awaiting_approval", owner="t", body="gated")
    nodes.create_node(conn, "Task", status="escalated", owner="t", body="stuck")
    counts = vm.overview_counts(conn)
    assert counts["gated_count"] == 1
    assert counts["escalation_count"] == 1


def test_board_view_survives_cyclic_implements(conn):
    a = nodes.create_node(conn, "Goal", status="open", owner="t", body="A")
    b = nodes.create_node(conn, "Epic", status="open", owner="t", body="B")
    relations.link_nodes(conn, b, a, "implements")   # b implements a (normal)
    relations.link_nodes(conn, a, b, "implements")   # a implements b (cycle!)
    model = vm.board_view(conn)  # must return, not RecursionError
    assert model.goals[0].node["id"] == a


def test_signals_view_findings_only_backlog(conn):
    parent = nodes.create_node(conn, "Task", status="pending", owner="t", body="p")
    nodes.create_node(conn, "Finding", status="open", owner="t", body="keep",
                      severity="Suggested", parent_id=parent, triage="backlog")
    nodes.create_node(conn, "Finding", status="open", owner="t", body="drop",
                      severity="Suggested", parent_id=parent, triage="fix-in-pr")
    model = vm.signals_view(conn)
    bodies = {f["body"] for f in model.findings}
    assert bodies == {"keep"}


def test_overview_counts_last_activity_present(conn):
    nodes.create_node(conn, "Task", status="pending", owner="t", body="t1")
    counts = vm.overview_counts(conn)
    assert counts["last_activity"] is not None

import pytest

from agentic_mcp import db, nodes, relations
from agentic_mcp.hud.daemon_client import DAEMON_OFFLINE
from agentic_mcp.hud.graph_source import GraphSource
from agentic_mcp.hud.app import AgenticHUD


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj" / ".agentic" / "graph.db"
    db.init_db(p)
    c = db.connect(p)
    goal = nodes.create_node(c, "Goal", status="open", owner="t", body="Goal A")
    epic = nodes.create_node(c, "Epic", status="open", owner="t", body="Epic A")
    task = nodes.create_node(c, "Task", status="pending", owner="t", body="Task A")
    relations.link_nodes(c, epic, goal, "implements")
    relations.link_nodes(c, task, epic, "implements")
    c.close()
    return {"path": str((tmp_path / "proj").as_posix()), "db": p}


class FakeDaemon:
    """Stubbed DaemonClient: records control calls, returns a canned snapshot."""
    def __init__(self, offline=False):
        self.offline = offline
        self.calls = []
    def snapshot(self):
        if self.offline:
            return DAEMON_OFFLINE
        return {"projects": [{"path": "P", "enabled": True, "paused": False,
                              "ticks": [{"tick": "orchestrate", "last_run": "now",
                                         "last_outcome": "ok"}]}],
                "beat_at": "now"}
    def run(self, path, tick): self.calls.append(("run", path, tick))
    def pause(self, path): self.calls.append(("pause", path))
    def resume(self, path): self.calls.append(("resume", path))


@pytest.fixture
def registry(project):
    return {"projects": [
        {"path": project["path"], "enabled": True, "scope_mode": "isolated",
         "cadences": {"orchestrate": "2m"}, "promotion_cap": 5}]}


async def test_overview_lists_projects(registry, project):
    app = AgenticHUD(registry=registry, daemon=FakeDaemon(),
                     sources={project["path"]: GraphSource(project["db"])},
                     start="overview")
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        assert table.row_count == 1


async def test_workspace_board_lists_task(registry, project):
    app = AgenticHUD(registry=registry, daemon=FakeDaemon(),
                     sources={project["path"]: GraphSource(project["db"])},
                     start="workspace", active_path=project["path"])
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = app.screen.board_text()
        assert "Task A" in rendered


async def test_daemon_offline_disables_controls(registry, project):
    app = AgenticHUD(registry=registry, daemon=FakeDaemon(offline=True),
                     sources={project["path"]: GraphSource(project["db"])},
                     start="workspace", active_path=project["path"])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.daemon_offline is True
        rendered = app.screen.board_text()
        assert "Task A" in rendered


async def test_run_now_invokes_daemon(registry, project):
    fake = FakeDaemon()
    app = AgenticHUD(registry=registry, daemon=fake,
                     sources={project["path"]: GraphSource(project["db"])},
                     start="workspace", active_path=project["path"])
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_run_now()
        assert ("run", project["path"], "orchestrate") in fake.calls


async def test_level_tab_narrows_board(registry, project):
    from textual.widgets import Tabs
    app = AgenticHUD(registry=registry, daemon=FakeDaemon(),
                     sources={project["path"]: GraphSource(project["db"])},
                     start="workspace", active_path=project["path"])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Task A" in app.screen.board_text()
        assert "Goal A" not in app.screen.board_text()
        app.screen.query_one(Tabs).active = "tab-Goal"
        await pilot.pause()
        assert "Goal A" in app.screen.board_text()
        assert "Task A" not in app.screen.board_text()


def test_find_project_root_walks_up(tmp_path):
    from agentic_mcp.hud.__main__ import _find_project_root
    from agentic_mcp import db
    root = tmp_path / "proj"
    db.init_db(root / ".agentic" / "graph.db")
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    assert _find_project_root(nested) == root


def test_find_project_root_bare_returns_none(tmp_path):
    from agentic_mcp.hud.__main__ import _find_project_root
    assert _find_project_root(tmp_path) is None


def test_build_sources_skips_missing_db(tmp_path):
    from agentic_mcp.hud.__main__ import _build_sources
    from agentic_mcp import db
    present = tmp_path / "present"
    db.init_db(present / ".agentic" / "graph.db")
    registry = {"projects": [
        {"path": str(present.as_posix())},
        {"path": str((tmp_path / "absent").as_posix())},
    ]}
    sources = _build_sources(registry)
    assert str(present.as_posix()) in sources
    assert str((tmp_path / "absent").as_posix()) not in sources
    for s in sources.values():
        s.close()


async def test_task_activation_opens_sheet_with_disabled_gate(registry, project):
    from agentic_mcp.hud.task_sheet import TaskSheet
    from textual.widgets import Button
    app = AgenticHUD(registry=registry, daemon=FakeDaemon(),
                     sources={project["path"]: GraphSource(project["db"])},
                     start="workspace", active_path=project["path"])
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.action_open_selected()  # selects first Task row -> push sheet
        await pilot.pause()
        assert isinstance(app.screen, TaskSheet)
        assert "Task A" in app.screen.sheet_text()
        approve = app.screen.query_one("#approve", Button)
        assert approve.disabled is True

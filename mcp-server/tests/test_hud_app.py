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

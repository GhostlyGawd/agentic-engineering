"""Textual screens. Dumb renderers of view-models; input wires to the app's
DaemonClient. No DB access here -- that is the view-model layer's job."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, Tab, Tabs

from . import view_models as vm

_LEVELS = ("Goal", "Epic", "Task", "Subtask")


class OverviewScreen(Screen):
    BINDINGS = [("enter", "open_workspace", "Open"),
                ("r", "run_now", "Run now"),
                ("space", "toggle_pause", "Pause/Resume")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="banner")
        yield DataTable(id="projects")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#projects", DataTable)
        table.add_columns("project", "ticks", "gated", "escalations", "last")
        self.refresh_view()

    def refresh_view(self) -> None:
        table = self.query_one("#projects", DataTable)
        table.clear()
        snap = self.app.last_snapshot
        for proj in self.app.registry.get("projects", []):
            path = proj["path"]
            src = self.app.sources.get(path)
            if src is None:
                table.add_row(path, "unavailable", "-", "-", "-")
                continue
            counts = vm.overview_counts(src.conn)
            ticks = self.app.ticks_summary(path, snap)
            table.add_row(path, ticks, str(counts["gated_count"]),
                          str(counts["escalation_count"]),
                          counts["last_activity"] or "--")
        self.query_one("#banner", Static).update(self.app.banner_text())

    def refresh_status(self) -> None:
        """Cheap every-tick update: live ticks/status changed but the graph
        did not. Re-render the banner (and tick column) without re-reading the
        board view-models."""
        self.refresh_view()


class WorkspaceScreen(Screen):
    BINDINGS = [("escape", "to_overview", "Overview"),
                ("r", "run_now", "Run now"),
                ("space", "toggle_pause", "Pause/Resume")]

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.level = "Task"
        self._rows: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="banner")
        yield Static(id="ticks")
        yield Tabs(*[Tab(lvl, id=f"tab-{lvl}") for lvl in _LEVELS],
                   active=f"tab-{self.level}")
        yield DataTable(id="board")
        yield Static(id="signals")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#board", DataTable).add_columns("id", "status", "body")
        self.refresh_view()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        # Derive level from the tab id ("tab-<Level>"); robust across textual
        # label-rendering changes (label may be a Text object, not a str).
        tab_id = getattr(event.tab, "id", None)
        if tab_id and tab_id.startswith("tab-"):
            self.level = tab_id[len("tab-"):]
        self.refresh_view()

    def refresh_view(self) -> None:
        src = self.app.sources.get(self.path)
        self.query_one("#banner", Static).update(self.app.banner_text())
        self.query_one("#ticks", Static).update(
            self.app.ticks_summary(self.path, self.app.last_snapshot))
        if src is None:
            self.query_one("#board", DataTable).clear()
            self._rows = []
            return
        board = vm.board_view(src.conn)
        table = self.query_one("#board", DataTable)
        table.clear()
        self._rows = []
        for node in board.by_level.get(self.level, []):
            self._rows.append(node)
            table.add_row(node["id"][:8], node.get("status", ""),
                          (node.get("body") or "")[:60])
        sig = vm.signals_view(src.conn)
        self.query_one("#signals", Static).update(
            f"patterns:{len(sig.patterns)}  archdebt:{len(sig.arch_debt)}  "
            f"distrusted:{sum(1 for c in sig.calibration if c.get('distrusted'))}")

    def refresh_status(self) -> None:
        """Cheap every-tick update: refresh the live banner + tick strip
        without re-reading the board/signals view-models from the DB."""
        self.query_one("#banner", Static).update(self.app.banner_text())
        self.query_one("#ticks", Static).update(
            self.app.ticks_summary(self.path, self.app.last_snapshot))

    def board_text(self) -> str:
        """Test helper: the rendered board rows as plain text."""
        return "\n".join(
            f"{n['id'][:8]} {n.get('status','')} {(n.get('body') or '')}"
            for n in getattr(self, "_rows", []))

    def selected_task_id(self):
        table = self.query_one("#board", DataTable)
        if self.level != "Task" or not getattr(self, "_rows", None):
            return None
        idx = table.cursor_row
        if idx is None or idx >= len(self._rows):
            return None
        return self._rows[idx]["id"]

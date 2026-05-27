"""AgenticHUD: the thin Textual application. Owns the single refresh timer +
thread worker, the daemon snapshot cache, and the offline flag. All DB and HTTP
work happens off the event loop (in the worker); widget updates are marshalled
back via call_from_thread."""
from __future__ import annotations

from textual.app import App

from .daemon_client import DAEMON_OFFLINE, DaemonClient
from .screens import OverviewScreen, WorkspaceScreen

REFRESH_SECONDS = 1.5


class AgenticHUD(App):
    def __init__(self, registry, daemon=None, sources=None,
                 start="overview", active_path=None):
        super().__init__()
        self.registry = registry
        self.daemon = daemon or DaemonClient()
        self.sources = sources or {}
        self._start = start
        self._active_path = active_path
        self.last_snapshot = None
        self.daemon_offline = False

    def on_mount(self) -> None:
        # Prime the snapshot + offline flag synchronously BEFORE the screen
        # mounts, so the screen's own on_mount->refresh_view renders the first
        # frame with correct state (deterministic under pilot.pause()). The
        # GraphSource baseline is primed too. Periodic refreshes after this go
        # through the thread worker (_poll), never the event loop.
        self._prime_state()
        if self._start == "workspace" and self._active_path:
            screen = WorkspaceScreen(self._active_path)
        else:
            screen = OverviewScreen()
        self.push_screen(screen)
        # Exactly ONE periodic timer for the whole app.
        self.set_interval(REFRESH_SECONDS, self._poll)

    def _prime_state(self) -> None:
        snap = self.daemon.snapshot()
        for src in self.sources.values():
            src.changed()  # prime the data_version baseline
        self.last_snapshot = None if snap is DAEMON_OFFLINE else snap
        self.daemon_offline = snap is DAEMON_OFFLINE

    def _poll(self) -> None:
        # Serialize via exclusive=True: the single read-only GraphSource
        # connection is never used by two refresh passes at once.
        self.run_worker(self._poll_worker, thread=True, exclusive=True)

    def _poll_worker(self) -> None:
        snap = self.daemon.snapshot()
        changed = any(src.changed() for src in self.sources.values())
        self.call_from_thread(self._apply_poll, snap, changed)

    def _apply_poll(self, snap, changed) -> None:
        self.last_snapshot = None if snap is DAEMON_OFFLINE else snap
        self.daemon_offline = snap is DAEMON_OFFLINE
        screen = self.screen
        # Health/tick strip + banner update every tick; the board re-reads the
        # view-models only when the graph changed (or on the first paint).
        if changed and hasattr(screen, "refresh_view"):
            screen.refresh_view()
        elif hasattr(screen, "refresh_status"):
            screen.refresh_status()

    def banner_text(self) -> str:
        return "DAEMON OFFLINE - read-only" if self.daemon_offline else "daemon healthy"

    def ticks_summary(self, path, snap) -> str:
        if not snap:
            return "(no live status)"
        for proj in snap.get("projects", []):
            if proj["path"] == path:
                return "  ".join(f"{t['tick']}:{t.get('last_outcome') or '-'}"
                                 for t in proj.get("ticks", [])) or "(no ticks)"
        return "(unknown)"

    def _first_tick(self, path) -> str:
        for proj in self.registry.get("projects", []):
            if proj["path"] == path:
                cad = proj.get("cadences", {})
                return next(iter(cad), "orchestrate")
        return "orchestrate"

    def _current_path(self):
        screen = self.screen
        return getattr(screen, "path", None) or self._active_path

    def action_run_now(self) -> None:
        if self.daemon_offline:
            return
        path = self._current_path()
        if path:
            self.daemon.run(path, self._first_tick(path))

    def action_toggle_pause(self) -> None:
        if self.daemon_offline:
            return
        path = self._current_path()
        if not path:
            return
        paused = False
        if self.last_snapshot:
            for proj in self.last_snapshot.get("projects", []):
                if proj["path"] == path:
                    paused = proj.get("paused", False)
        (self.daemon.resume if paused else self.daemon.pause)(path)

    def action_open_workspace(self) -> None:
        first = self.registry.get("projects", [])
        if first:
            self.push_screen(WorkspaceScreen(first[0]["path"]))

    def action_to_overview(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()

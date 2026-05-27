"""Read-only task drill-in. Approve/Decline/Retry are rendered but DISABLED --
the rung-3 approval gate enables them and wires the new control endpoints."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from . import view_models as vm

_RUNG3_NOTE = "Approve/Decline/Retry arrive in rung 3"


def _crit_line(c):
    """Format one criterion. Canonical shape is a dict
    {text, verify, satisfied, evidence}; fall back to str for legacy data."""
    if isinstance(c, dict):
        mark = "x" if c.get("satisfied") else " "
        return f"  [{mark}] {c.get('text', '')}"
    return f"  - {c}"


class TaskSheet(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, conn, task_id: str):
        super().__init__()
        self.model = vm.task_sheet_view(conn, task_id)

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(self._text(), id="sheet")
            with Horizontal():
                yield Button("Approve", id="approve", disabled=True,
                             tooltip=_RUNG3_NOTE)
                yield Button("Decline", id="decline", disabled=True,
                             tooltip=_RUNG3_NOTE)
                yield Button("Retry", id="retry", disabled=True,
                             tooltip=_RUNG3_NOTE)
            yield Static(_RUNG3_NOTE, id="gate-note")

    def _text(self) -> str:
        m = self.model
        if m.task is None:
            # The task vanished mid-session (deleted/compacted). Render a stub
            # rather than KeyError on m.task['id'].
            return "TASK (not found)\nThis task no longer exists in the graph."
        lines = [f"TASK {m.task['id']}  [{m.task.get('status', '')}]",
                 m.task.get("body") or "",
                 "",
                 "CRITERIA:"]
        crit_lines = [_crit_line(c) for c in m.criteria] or ["  (none)"]
        lines += crit_lines
        lines += ["",
                  f"ORIGIN: {m.origin_signal['id'] if m.origin_signal else '(none)'}",
                  f"PARENT: {m.parent['id'] if m.parent else '(none)'}",
                  f"REVIEWS: {len(m.reviews)}"]
        return "\n".join(lines)

    def sheet_text(self) -> str:
        """Test helper: the rendered sheet text."""
        return self._text()

    def action_close(self) -> None:
        self.dismiss()

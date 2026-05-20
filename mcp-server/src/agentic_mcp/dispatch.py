"""dispatch_spec: stamp dispatched_at (drives criteria immutability)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import nodes


def dispatch_spec(conn: sqlite3.Connection, spec_id: str) -> str:
    spec = nodes.get_node(conn, spec_id)
    if spec is None or spec["type"] != "Spec":
        raise ValueError(f"not a Spec node: {spec_id}")
    if spec.get("dispatched_at"):
        return spec["dispatched_at"]  # already dispatched, no-op
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nodes.update_node(conn, spec_id, dispatched_at=stamp)
    return stamp

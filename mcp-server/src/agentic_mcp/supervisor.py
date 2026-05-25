"""The supervisor: a logic-free scheduler that fires existing ticks on cadence.

scheduler_pass is the pure, stateless core (mirrors orchestrate.tick): given a
registry + state connection + a clock + a spawn seam, it fires every due tick for
every enabled, non-paused project and records the outcome. It NEVER raises -- a
failed spawn is an outcome recorded in result["errors"]. The run_forever loop and
CLI (Tasks 6-7) wrap this; nothing here knows about HTTP or threads.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import supervisor_config as cfg
from . import supervisor_state as st
from . import tick_spawn


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def scheduler_pass(registry: dict, state_conn, *, now: datetime | None = None,
                   spawn_fn=None) -> dict:
    """Fire every due tick once. Returns {fired, skipped, errors}. Never raises."""
    now = now or _now_utc()
    spawn_fn = spawn_fn or (lambda path, tick: tick_spawn.spawn_tick(path, tick))
    result = {"fired": [], "skipped": [], "errors": []}

    for proj in registry.get("projects", []):
        path = proj["path"]
        key_proj = path
        if not proj.get("enabled", True) or st.is_paused(state_conn, path):
            result["skipped"].append(f"{key_proj}:(project disabled/paused)")
            continue
        for tick, cadence in proj.get("cadences", {}).items():
            label = f"{path}:{tick}"
            try:
                last = st.get_last_run(state_conn, path, tick)
                if not cfg.is_due(last, cadence, now):
                    result["skipped"].append(label)
                    continue
            except ValueError as e:  # bad cadence string -> log, do not crash
                result["errors"].append({"task": label, "error": str(e)})
                continue
            outcome = spawn_fn(path, tick)
            stamp = now.isoformat(timespec="seconds")
            st.record_run(state_conn, path, tick, stamp,
                          "ok" if outcome.get("ok") else outcome.get("error", "error"))
            if outcome.get("ok"):
                result["fired"].append(label)
            else:
                result["errors"].append({"task": label,
                                         "error": outcome.get("error", "error")})
    return result

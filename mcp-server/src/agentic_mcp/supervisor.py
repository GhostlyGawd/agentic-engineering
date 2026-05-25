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


import argparse
import json
import sys
import time

from . import control_api

_POLL_SECONDS = 15
_DEFAULT_PORT = 8787


def run_once(*, registry_path=None, state_path=None, now=None, spawn_fn=None) -> dict:
    """Open state, run one scheduler pass, write the heartbeat, return the result."""
    registry_path = registry_path or cfg.default_registry_path()
    state_path = state_path or st.default_state_path()
    registry = cfg.load_registry(registry_path)
    conn = st.connect_state(state_path)
    try:
        now = now or _now_utc()
        result = scheduler_pass(registry, conn, now=now, spawn_fn=spawn_fn)
        st.beat(conn, now.isoformat(timespec="seconds"))
        return result
    finally:
        conn.close()


def run_forever(*, registry_path=None, state_path=None, port=_DEFAULT_PORT,
                poll_seconds=_POLL_SECONDS) -> None:  # pragma: no cover - loop
    """Start the control API thread, then loop scheduler passes until interrupted."""
    registry_path = registry_path or cfg.default_registry_path()
    state_path = state_path or st.default_state_path()
    server = control_api.build_server(
        registry_loader=lambda: cfg.load_registry(registry_path),
        state_path=state_path,
        run_fn=lambda path, tick: tick_spawn.spawn_tick(path, tick),
        port=port,
    )
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while True:
            run_once(registry_path=registry_path, state_path=state_path)
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        server.shutdown()


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # cp1252 default on this box
    parser = argparse.ArgumentParser(prog="agentic-supervisor")
    parser.add_argument("--once", action="store_true",
                        help="run a single scheduler pass and exit")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT,
                        help="loopback control API port (run-forever mode)")
    args = parser.parse_args(argv)
    if args.once:
        print(json.dumps(run_once(), default=str))
        return 0
    run_forever(port=args.port)  # pragma: no cover
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

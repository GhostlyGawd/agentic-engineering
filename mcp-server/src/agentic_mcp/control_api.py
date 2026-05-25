"""Loopback (127.0.0.1) control + health API for the supervisor.

stdlib http.server only (no new dependency). Read endpoints serve the HUD's
overview; write endpoints (run-now, pause/resume) are the clickable controls.
Approve/decline/retry are intentionally NOT here yet -- they belong to the
approval gate (rung 3) and need task states that do not exist in rung 1.
Bound to 127.0.0.1 so the surface is never reachable off-host.
"""
from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import supervisor_config as cfg
from . import supervisor_state as st


def build_server(*, registry_loader=None, state_path=None, run_fn=None, port=0):
    """Construct (do not start) a ThreadingHTTPServer bound to 127.0.0.1.

    Seams: registry_loader() -> registry dict; run_fn(path, tick) triggers a
    spawn (the loop wires this to a backgrounded tick_spawn). Tests inject both.
    """
    registry_loader = registry_loader or (
        lambda: cfg.load_registry(cfg.default_registry_path()))
    state_path = state_path or st.default_state_path()
    run_fn = run_fn or (lambda path, tick: None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence default stderr logging
            pass

        def _send(self, code, payload):
            body = json.dumps(payload, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            conn = st.connect_state(state_path)
            try:
                if self.path == "/health":
                    self._send(200, {"status": "ok", "beat_at": st.last_beat(conn)})
                elif self.path == "/projects":
                    self._send(200, self._projects(conn))
                else:
                    self._send(404, {"error": "not found"})
            finally:
                conn.close()

        def do_POST(self):
            parts = [urllib.parse.unquote(p) for p in self.path.strip("/").split("/")]
            conn = st.connect_state(state_path)
            try:
                # /projects/{path}/pause | resume | run/{tick}
                if len(parts) >= 3 and parts[0] == "projects":
                    project = parts[1]
                    action = parts[2]
                    if action == "pause":
                        st.set_paused(conn, project); self._send(200, {"paused": True}); return
                    if action == "resume":
                        st.clear_paused(conn, project); self._send(200, {"paused": False}); return
                    if action == "run" and len(parts) >= 4:
                        run_fn(project, parts[3]); self._send(202, {"queued": parts[3]}); return
                self._send(404, {"error": "not found"})
            finally:
                conn.close()

        def _projects(self, conn):
            reg = registry_loader()
            state = {(r["project"], r["tick"]): r for r in st.all_state(conn)}
            out = []
            for proj in reg.get("projects", []):
                path = proj["path"]
                ticks = []
                for tick in proj.get("cadences", {}):
                    s = state.get((path, tick), {})
                    ticks.append({"tick": tick, "last_run": s.get("last_run"),
                                  "last_outcome": s.get("last_outcome")})
                out.append({"path": path, "enabled": proj["enabled"],
                            "paused": st.is_paused(conn, path), "ticks": ticks})
            return {"projects": out, "beat_at": st.last_beat(conn)}

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)

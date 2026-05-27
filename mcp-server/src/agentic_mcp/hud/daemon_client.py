"""Loopback client for the rung-1 supervisor control API.

Any transport failure returns the DAEMON_OFFLINE sentinel -- the HUD degrades to
read-only rather than crashing. Approve/decline/retry are NOT here: those
endpoints belong to the rung-3 approval gate."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class _Offline:
    """Singleton sentinel: the daemon is unreachable."""
    def __repr__(self) -> str:
        return "DAEMON_OFFLINE"
    def __bool__(self) -> bool:
        return False


DAEMON_OFFLINE = _Offline()

_DEFAULT_PORT = 8787


def _resolve_port(port: int | None) -> int:
    if port is not None:
        return port
    return int(os.environ.get("AGENTIC_SUPERVISOR_PORT", str(_DEFAULT_PORT)))


class DaemonClient:
    def __init__(self, port: int | None = None, timeout: float = 0.5):
        self.base = f"http://127.0.0.1:{_resolve_port(port)}"
        self.timeout = timeout

    def _call(self, path: str, method: str = "GET"):
        url = self.base + path
        try:
            req = urllib.request.Request(
                url, method=method, data=(b"" if method == "POST" else None))
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, OSError, ValueError):
            return DAEMON_OFFLINE

    def snapshot(self):
        return self._call("/projects")

    def health(self):
        return self._call("/health")

    def run(self, path: str, tick: str):
        q = urllib.parse.quote(path, safe="")
        return self._call(f"/projects/{q}/run/{tick}", method="POST")

    def pause(self, path: str):
        q = urllib.parse.quote(path, safe="")
        return self._call(f"/projects/{q}/pause", method="POST")

    def resume(self, path: str):
        q = urllib.parse.quote(path, safe="")
        return self._call(f"/projects/{q}/resume", method="POST")

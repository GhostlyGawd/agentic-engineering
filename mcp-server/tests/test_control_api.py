import json
import urllib.parse
import urllib.request

import pytest

from agentic_mcp import control_api, supervisor_state as st


@pytest.fixture
def server(tmp_path):
    reg = {"projects": [
        {"path": "C:/p", "enabled": True, "scope_mode": "isolated",
         "cadences": {"orchestrate": "2m"}, "promotion_cap": 5}]}
    fired = []
    srv = control_api.build_server(
        registry_loader=lambda: reg,
        state_path=tmp_path / "s.db",
        run_fn=lambda path, tick: fired.append((path, tick)),
        port=0,  # ephemeral
    )
    srv.fired = fired
    import threading
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


def _get(srv, path):
    host, port = srv.server_address
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        return r.status, json.loads(r.read().decode())


def _post(srv, path):
    host, port = srv.server_address
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST", data=b"")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read().decode())


def test_health(server):
    status, body = _get(server, "/health")
    assert status == 200
    assert body["status"] == "ok"


def test_projects_lists_registry(server):
    status, body = _get(server, "/projects")
    assert status == 200
    assert body["projects"][0]["path"] == "C:/p"
    assert body["projects"][0]["paused"] is False


def test_pause_resume(server):
    q = urllib.parse.quote("C:/p", safe="")
    _post(server, f"/projects/{q}/pause")
    _, body = _get(server, "/projects")
    assert body["projects"][0]["paused"] is True
    _post(server, f"/projects/{q}/resume")
    _, body = _get(server, "/projects")
    assert body["projects"][0]["paused"] is False


def test_run_now_triggers_spawn(server):
    q = urllib.parse.quote("C:/p", safe="")
    status, _ = _post(server, f"/projects/{q}/run/orchestrate")
    assert status == 202
    assert server.fired == [("C:/p", "orchestrate")]


def test_binds_loopback_only(server):
    assert server.server_address[0] == "127.0.0.1"

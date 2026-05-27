import threading

import pytest

from agentic_mcp import control_api
from agentic_mcp.hud.daemon_client import DaemonClient, DAEMON_OFFLINE


@pytest.fixture
def live(tmp_path):
    reg = {"projects": [
        {"path": "C:/p", "enabled": True, "scope_mode": "isolated",
         "cadences": {"orchestrate": "2m"}, "promotion_cap": 5}]}
    fired = []
    srv = control_api.build_server(
        registry_loader=lambda: reg, state_path=tmp_path / "s.db",
        run_fn=lambda path, tick: fired.append((path, tick)), port=0)
    srv.fired = fired
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


def test_port_resolution_default(monkeypatch):
    monkeypatch.delenv("AGENTIC_SUPERVISOR_PORT", raising=False)
    assert DaemonClient().base.endswith(":8787")


def test_port_resolution_env(monkeypatch):
    monkeypatch.setenv("AGENTIC_SUPERVISOR_PORT", "9001")
    assert DaemonClient().base.endswith(":9001")


def test_snapshot_against_live_server(live):
    port = live.server_address[1]
    client = DaemonClient(port=port)
    snap = client.snapshot()
    assert snap is not DAEMON_OFFLINE
    assert snap["projects"][0]["path"] == "C:/p"


def test_run_against_live_server(live):
    port = live.server_address[1]
    DaemonClient(port=port).run("C:/p", "orchestrate")
    assert live.fired == [("C:/p", "orchestrate")]


def test_offline_returns_sentinel():
    # 9 is the discard port -- nothing listens; connection fails fast.
    client = DaemonClient(port=9, timeout=0.2)
    assert client.snapshot() is DAEMON_OFFLINE
    assert client.pause("C:/p") is DAEMON_OFFLINE  # does not raise


def test_no_gate_methods():
    client = DaemonClient(port=9)
    for forbidden in ("approve", "decline", "retry"):
        assert not hasattr(client, forbidden)

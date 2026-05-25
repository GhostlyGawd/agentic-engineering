import json
from datetime import datetime, timezone

from agentic_mcp import supervisor


def _write_reg(tmp_path):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"projects": [
        {"path": "C:/p", "enabled": True, "cadences": {"orchestrate": "2m"}}]}),
        encoding="utf-8")
    return reg


def test_run_once_fires_and_beats(tmp_path):
    reg = _write_reg(tmp_path)
    state = tmp_path / "s.db"
    fired = []
    res = supervisor.run_once(
        registry_path=reg, state_path=state,
        now=datetime(2026, 5, 25, tzinfo=timezone.utc),
        spawn_fn=lambda path, tick: (fired.append(tick) or {"ok": True, "tick": tick}),
    )
    assert res["fired"] == ["C:/p:orchestrate"]
    assert fired == ["orchestrate"]
    # heartbeat was written
    from agentic_mcp import supervisor_state as st
    conn = st.connect_state(state)
    assert st.last_beat(conn) is not None
    conn.close()


def test_main_once_returns_zero(tmp_path, monkeypatch, capsys):
    reg = _write_reg(tmp_path)
    monkeypatch.setenv("AGENTIC_REGISTRY_PATH", str(reg))
    monkeypatch.setenv("AGENTIC_SUPERVISOR_DB", str(tmp_path / "s.db"))
    # Avoid real subprocess: stub the spawner used by the default pass.
    monkeypatch.setattr(supervisor.tick_spawn, "spawn_tick",
                        lambda path, tick, **k: {"ok": True, "tick": tick})
    rc = supervisor.main(["--once"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "fired" in out

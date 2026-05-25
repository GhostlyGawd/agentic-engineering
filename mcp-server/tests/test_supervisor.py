from datetime import datetime, timezone

from agentic_mcp import supervisor, supervisor_state as st


def _reg(cadences, enabled=True):
    return {"projects": [
        {"path": "C:/p", "enabled": enabled, "scope_mode": "isolated",
         "cadences": cadences, "promotion_cap": 5},
    ]}


def _now():
    return datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)


def test_pass_fires_due_tick(tmp_path):
    conn = st.connect_state(tmp_path / "s.db")
    fired = []
    spawn = lambda path, tick: (fired.append((path, tick)) or {"ok": True, "tick": tick})
    res = supervisor.scheduler_pass(_reg({"orchestrate": "2m"}), conn,
                                    now=_now(), spawn_fn=spawn)
    assert fired == [("C:/p", "orchestrate")]
    assert res["fired"] == ["C:/p:orchestrate"]
    # last_run was recorded, so a second pass at the same instant does not refire.
    res2 = supervisor.scheduler_pass(_reg({"orchestrate": "2m"}), conn,
                                     now=_now(), spawn_fn=spawn)
    assert res2["fired"] == []
    conn.close()


def test_pass_skips_disabled_and_paused(tmp_path):
    conn = st.connect_state(tmp_path / "s.db")
    spawn = lambda path, tick: {"ok": True, "tick": tick}
    res = supervisor.scheduler_pass(_reg({"orchestrate": "2m"}, enabled=False),
                                    conn, now=_now(), spawn_fn=spawn)
    assert res["fired"] == []

    st.set_paused(conn, "C:/p")
    res2 = supervisor.scheduler_pass(_reg({"orchestrate": "2m"}), conn,
                                     now=_now(), spawn_fn=spawn)
    assert res2["fired"] == []
    conn.close()


def test_pass_skips_unknown_tick_name(tmp_path):
    conn = st.connect_state(tmp_path / "s.db")
    # 'arch_review' has no CLI yet -> spawn_tick returns ok:false -> errors.
    res = supervisor.scheduler_pass(_reg({"arch_review": "1d"}), conn,
                                    now=_now())  # real spawn_tick default
    assert res["fired"] == []
    assert res["errors"] and "unknown tick" in res["errors"][0]["error"]
    conn.close()


def test_pass_records_failure_outcome(tmp_path):
    conn = st.connect_state(tmp_path / "s.db")
    spawn = lambda path, tick: {"ok": False, "tick": tick, "error": "boom"}
    res = supervisor.scheduler_pass(_reg({"orchestrate": "2m"}), conn,
                                    now=_now(), spawn_fn=spawn)
    assert res["fired"] == []
    assert res["errors"][0]["error"] == "boom"
    assert st.all_state(conn)[0]["last_outcome"] == "boom"
    conn.close()

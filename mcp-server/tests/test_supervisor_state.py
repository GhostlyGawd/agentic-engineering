from agentic_mcp import supervisor_state as st


def test_record_and_get_last_run(tmp_path):
    conn = st.connect_state(tmp_path / "supervisor.db")
    assert st.get_last_run(conn, "C:/p", "orchestrate") is None
    st.record_run(conn, "C:/p", "orchestrate", "2026-05-25T12:00:00+00:00", "ok")
    assert st.get_last_run(conn, "C:/p", "orchestrate") == "2026-05-25T12:00:00+00:00"
    rows = st.all_state(conn)
    assert rows[0]["last_outcome"] == "ok"
    conn.close()


def test_heartbeat_roundtrip(tmp_path):
    conn = st.connect_state(tmp_path / "supervisor.db")
    assert st.last_beat(conn) is None
    st.beat(conn, "2026-05-25T12:00:01+00:00")
    assert st.last_beat(conn) == "2026-05-25T12:00:01+00:00"
    conn.close()


def test_pause_flags(tmp_path):
    conn = st.connect_state(tmp_path / "supervisor.db")
    assert st.is_paused(conn, "C:/p") is False
    st.set_paused(conn, "C:/p")
    assert st.is_paused(conn, "C:/p") is True
    st.clear_paused(conn, "C:/p")
    assert st.is_paused(conn, "C:/p") is False
    conn.close()


def test_connect_state_idempotent(tmp_path):
    p = tmp_path / "supervisor.db"
    st.connect_state(p).close()
    conn = st.connect_state(p)  # second open must not raise
    st.beat(conn, "2026-05-25T00:00:00+00:00")
    conn.close()

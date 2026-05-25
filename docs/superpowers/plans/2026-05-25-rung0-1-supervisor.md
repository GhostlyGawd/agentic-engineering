# Rung 0 + Rung 1: busy_timeout + Supervisor Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the always-on foundation: make `db.connect` wait on lock contention, then add a logic-free supervisor daemon that fires the existing stateless ticks (`orchestrate`, `pattern_finder`) on per-project cadences and serves a loopback health/control API.

**Architecture:** The supervisor is a scheduler + health server with NO LLM and NO graph-business-logic. It reads a project registry (`~/.agentic/registry.json`), and on each project's cadence spawns the EXISTING tick CLIs as short-lived subprocesses against that project's `graph.db`. Durable truth stays in each project's `graph.db`; the supervisor keeps only ephemeral runtime state (`~/.agentic/supervisor.db`). A stdlib `http.server` on `127.0.0.1` exposes health/projects/run-now/pause. The OS scheduler keeps the daemon alive.

**Tech Stack:** Python 3.12, stdlib only (`sqlite3`, `subprocess`, `http.server`, `threading`, `argparse`) — no new runtime dependency beyond the existing `mcp`. pytest (fast suite is the gate; no `llm`-marked tests needed for this rung).

---

## File Structure

New + modified files (all under `mcp-server/`):

- Modify: `src/agentic_mcp/db.py` — add `PRAGMA busy_timeout` in `connect`.
- Create: `src/agentic_mcp/supervisor_config.py` — registry.json load/validate + cadence parsing + due-calculation (config interpretation).
- Create: `src/agentic_mcp/supervisor_state.py` — ephemeral runtime state store (`supervisor.db`): last_run/outcome, heartbeat, runtime pause flags.
- Create: `src/agentic_mcp/tick_spawn.py` — tick-name -> CLI argv mapping + the subprocess spawner (the only thing that runs a child process).
- Create: `src/agentic_mcp/supervisor.py` — the pure `scheduler_pass` core, the `run_forever` loop, `main()` + console script.
- Create: `src/agentic_mcp/control_api.py` — loopback `http.server` control surface.
- Create: `scripts/install-supervisor.ps1` — Windows Task Scheduler keep-alive registration (ASCII-only; `-Print` dry-run).
- Modify: `pyproject.toml` — add `agentic-supervisor` console script.
- Create test files mirroring each module under `tests/`.

Naming note: the existing `registry.py` is the unrelated plugin known-overlap table. The supervisor's project list is `supervisor_config.py` reading `~/.agentic/registry.json` (a config file, not that module).

---

### Task 0: Add `PRAGMA busy_timeout` to `db.connect`

**Goal:** Concurrent connections (daemon tick + HUD read) wait up to 5s on a lock instead of failing immediately with `database is locked`.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/db.py:17-22`
- Test: `mcp-server/tests/test_db.py`

**Acceptance Criteria:**
- [ ] Every connection from `db.connect` has `busy_timeout` set to 5000 ms.
- [ ] Existing db tests still pass.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_db.py -q` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing test**

Add to `mcp-server/tests/test_db.py`:

```python
def test_connect_sets_busy_timeout(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = db.connect(tmp_db_path)
    try:
        # PRAGMA busy_timeout returns the current value in milliseconds.
        (value,) = conn.execute("PRAGMA busy_timeout").fetchone()
        assert value == 5000
    finally:
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_db.py::test_connect_sets_busy_timeout -v`
Expected: FAIL (value is the SQLite default 0, not 5000)

- [ ] **Step 3: Write minimal implementation**

In `mcp-server/src/agentic_mcp/db.py`, edit `connect`:

```python
def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection. Caller manages close()."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    # Cross-process contention is now by-design (the supervisor's tick
    # connections vs the HUD's read connections). Wait on a held lock instead
    # of failing fast with 'database is locked'.
    conn.execute("PRAGMA busy_timeout = 5000")
    migrations.apply_migrations(conn)  # upgrade existing DBs on open
    return conn
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_db.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/db.py mcp-server/tests/test_db.py
git commit -m "feat(db): set busy_timeout=5000 in connect for concurrent access"
```

---

### Task 1: Registry config + cadence parsing (`supervisor_config.py`)

**Goal:** Load and validate `~/.agentic/registry.json`, and provide pure cadence parsing + due-calculation.

**Files:**
- Create: `mcp-server/src/agentic_mcp/supervisor_config.py`
- Test: `mcp-server/tests/test_supervisor_config.py`

**Acceptance Criteria:**
- [ ] `default_registry_path()` resolves `AGENTIC_REGISTRY_PATH` or `~/.agentic/registry.json`.
- [ ] `load_registry(path)` returns a normalized dict with defaults applied; raises `ValueError` on malformed JSON or a non-list `projects`.
- [ ] `parse_cadence` handles `Ns/Nm/Nh/Nd/Nw` + aliases `hourly/daily/weekly`; raises `ValueError` otherwise.
- [ ] `is_due(last_run, cadence, now)` returns True when never run or when elapsed >= cadence seconds.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_config.py -q` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_supervisor_config.py`:

```python
import json
from datetime import datetime, timedelta, timezone

import pytest

from agentic_mcp import supervisor_config as cfg


def test_default_registry_path_env_override(tmp_path, monkeypatch):
    target = tmp_path / "reg.json"
    monkeypatch.setenv("AGENTIC_REGISTRY_PATH", str(target))
    assert cfg.default_registry_path() == target.resolve()


def test_load_registry_applies_defaults(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"projects": [{"path": "C:/proj"}]}), encoding="utf-8")
    reg = cfg.load_registry(p)
    proj = reg["projects"][0]
    assert proj["enabled"] is True
    assert proj["scope_mode"] == "isolated"
    assert proj["cadences"] == {}


def test_load_registry_missing_file_is_empty(tmp_path):
    reg = cfg.load_registry(tmp_path / "nope.json")
    assert reg == {"projects": []}


def test_load_registry_malformed_raises(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        cfg.load_registry(p)


def test_load_registry_non_list_projects_raises(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"projects": "x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        cfg.load_registry(p)


@pytest.mark.parametrize("text,seconds", [
    ("30s", 30), ("2m", 120), ("6h", 21600), ("1d", 86400),
    ("1w", 604800), ("hourly", 3600), ("daily", 86400), ("weekly", 604800),
])
def test_parse_cadence(text, seconds):
    assert cfg.parse_cadence(text) == seconds


@pytest.mark.parametrize("bad", ["", "5", "m", "10x", "-3m", "1.5h"])
def test_parse_cadence_bad_raises(bad):
    with pytest.raises(ValueError):
        cfg.parse_cadence(bad)


def test_is_due_never_run():
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    assert cfg.is_due(None, "2m", now) is True


def test_is_due_elapsed():
    now = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    last = (now - timedelta(minutes=3)).isoformat()
    assert cfg.is_due(last, "2m", now) is True


def test_is_due_not_yet():
    now = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    last = (now - timedelta(seconds=30)).isoformat()
    assert cfg.is_due(last, "2m", now) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_config.py -v`
Expected: FAIL with "No module named 'agentic_mcp.supervisor_config'"

- [ ] **Step 3: Write the implementation**

Create `mcp-server/src/agentic_mcp/supervisor_config.py`:

```python
"""Supervisor configuration: project registry + cadence interpretation.

Pure config logic. The registry (~/.agentic/registry.json) lists which projects
the supervisor daemon watches and at what cadence. This module does no I/O beyond
reading that one file and no process work. Distinct from registry.py (the
unrelated plugin known-overlap table).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

_CADENCE_RE = re.compile(r"^(\d+)([smhdw])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_ALIASES = {"hourly": 3600, "daily": 86400, "weekly": 604800}


def default_registry_path() -> Path:
    raw = os.environ.get("AGENTIC_REGISTRY_PATH")
    if raw:
        return Path(raw).resolve()
    return (Path.home() / ".agentic" / "registry.json").resolve()


def load_registry(path: str | Path) -> dict:
    """Return {"projects": [normalized...]}. Missing file -> empty. Malformed
    JSON or a non-list projects -> ValueError (a startup config error, fail loud)."""
    p = Path(path)
    if not p.exists():
        return {"projects": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise ValueError(f"malformed registry {p}: {e}") from e
    projects = data.get("projects", [])
    if not isinstance(projects, list):
        raise ValueError(f"registry {p}: 'projects' must be a list")
    return {"projects": [_normalize_project(x) for x in projects]}


def _normalize_project(raw: dict) -> dict:
    if not isinstance(raw, dict) or "path" not in raw:
        raise ValueError(f"registry project missing 'path': {raw!r}")
    return {
        "path": str(raw["path"]),
        "enabled": bool(raw.get("enabled", True)),
        "scope_mode": str(raw.get("scope_mode", "isolated")),
        "cadences": dict(raw.get("cadences", {})),
        "promotion_cap": int(raw.get("promotion_cap", 5)),
    }


def parse_cadence(text: str) -> int:
    """Cadence string -> seconds. Grammar: Ns/Nm/Nh/Nd/Nw, plus aliases."""
    if text in _ALIASES:
        return _ALIASES[text]
    m = _CADENCE_RE.match(text or "")
    if not m:
        raise ValueError(f"bad cadence: {text!r}")
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)]


def is_due(last_run: str | None, cadence: str, now: datetime) -> bool:
    """True if the tick has never run or enough time has elapsed since last_run."""
    if not last_run:
        return True
    last = datetime.fromisoformat(last_run)
    return (now - last).total_seconds() >= parse_cadence(cadence)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_config.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/supervisor_config.py mcp-server/tests/test_supervisor_config.py
git commit -m "feat(supervisor): registry load/validate + cadence parsing"
```

---

### Task 2: Ephemeral runtime state store (`supervisor_state.py`)

**Goal:** A small SQLite store for per-tick last_run/outcome, a heartbeat, and runtime pause flags. Holds NO durable project data; safe to delete.

**Files:**
- Create: `mcp-server/src/agentic_mcp/supervisor_state.py`
- Test: `mcp-server/tests/test_supervisor_state.py`

**Acceptance Criteria:**
- [ ] `connect_state(path)` creates the schema on first open (idempotent).
- [ ] `record_run(conn, project, tick, last_run, outcome)` upserts; `get_last_run` reads it back.
- [ ] `beat`/`last_beat` round-trip a heartbeat timestamp.
- [ ] `set_paused`/`clear_paused`/`is_paused` toggle a runtime pause flag per project.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_state.py -q` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_supervisor_state.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_state.py -v`
Expected: FAIL with "No module named 'agentic_mcp.supervisor_state'"

- [ ] **Step 3: Write the implementation**

Create `mcp-server/src/agentic_mcp/supervisor_state.py`:

```python
"""Ephemeral supervisor runtime state (~/.agentic/supervisor.db).

Holds ONLY: per-(project,tick) last_run + last_outcome + last_pid, a single
heartbeat row, and runtime pause flags. NO durable project data lives here -- if
deleted, the daemon rebuilds it (worst case: a tick fires early). Created on the
fly with CREATE TABLE IF NOT EXISTS (no migration framework).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS tick_state (
  project TEXT NOT NULL,
  tick TEXT NOT NULL,
  last_run TEXT,
  last_outcome TEXT,
  last_pid INTEGER,
  PRIMARY KEY (project, tick)
);
CREATE TABLE IF NOT EXISTS heartbeat (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  beat_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paused (
  project TEXT PRIMARY KEY
);
"""


def default_state_path() -> Path:
    raw = os.environ.get("AGENTIC_SUPERVISOR_DB")
    if raw:
        return Path(raw).resolve()
    return (Path.home() / ".agentic" / "supervisor.db").resolve()


def connect_state(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_DDL)
    conn.commit()
    return conn


def record_run(conn, project: str, tick: str, last_run: str, outcome: str,
               pid: int | None = None) -> None:
    conn.execute(
        "INSERT INTO tick_state(project, tick, last_run, last_outcome, last_pid) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(project, tick) DO UPDATE SET "
        "last_run=excluded.last_run, last_outcome=excluded.last_outcome, "
        "last_pid=excluded.last_pid",
        (project, tick, last_run, outcome, pid),
    )
    conn.commit()


def get_last_run(conn, project: str, tick: str) -> str | None:
    row = conn.execute(
        "SELECT last_run FROM tick_state WHERE project=? AND tick=?",
        (project, tick),
    ).fetchone()
    return row[0] if row else None


def all_state(conn) -> list[dict]:
    cols = ["project", "tick", "last_run", "last_outcome", "last_pid"]
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT project, tick, last_run, last_outcome, last_pid FROM tick_state "
        "ORDER BY project, tick")]


def beat(conn, beat_at: str) -> None:
    conn.execute(
        "INSERT INTO heartbeat(id, beat_at) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET beat_at=excluded.beat_at",
        (beat_at,),
    )
    conn.commit()


def last_beat(conn) -> str | None:
    row = conn.execute("SELECT beat_at FROM heartbeat WHERE id=1").fetchone()
    return row[0] if row else None


def set_paused(conn, project: str) -> None:
    conn.execute("INSERT OR IGNORE INTO paused(project) VALUES (?)", (project,))
    conn.commit()


def clear_paused(conn, project: str) -> None:
    conn.execute("DELETE FROM paused WHERE project=?", (project,))
    conn.commit()


def is_paused(conn, project: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM paused WHERE project=?", (project,)
    ).fetchone() is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_state.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/supervisor_state.py mcp-server/tests/test_supervisor_state.py
git commit -m "feat(supervisor): ephemeral runtime state store"
```

---

### Task 3: Tick spawner (`tick_spawn.py`)

**Goal:** Map a tick name to the existing CLI argv and spawn it as a short-lived subprocess against a project's graph.db. Never raises; returns an outcome dict.

**Files:**
- Create: `mcp-server/src/agentic_mcp/tick_spawn.py`
- Test: `mcp-server/tests/test_tick_spawn.py`

**Acceptance Criteria:**
- [ ] `TICK_COMMANDS` maps only EXISTING CLIs: `orchestrate` -> `agentic_mcp.orchestrate`, `pattern_finder` -> `agentic_mcp.patterns` (both `--once`).
- [ ] `spawn_tick` sets `AGENTIC_DB_PATH` to `<project>/.agentic/graph.db`, `cwd=<project>`, uses `sys.executable -m <module>`, and injects a `runner` seam.
- [ ] Unknown tick -> `{"ok": False, "error": ...}` without spawning.
- [ ] A runner raising -> `{"ok": False, "error": ...}` (never raises).

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_tick_spawn.py -q` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_tick_spawn.py`:

```python
import sys
from pathlib import Path

from agentic_mcp import tick_spawn


def _fake_runner_factory(record):
    def runner(argv, cwd, env):
        record["argv"] = argv
        record["cwd"] = cwd
        record["env"] = env
        class R:
            returncode = 0
            stdout = '{"ok": true}'
            stderr = ""
        return R()
    return runner


def test_spawn_tick_builds_argv_and_env(tmp_path):
    rec = {}
    proj = str(tmp_path / "proj")
    out = tick_spawn.spawn_tick(proj, "orchestrate",
                                runner=_fake_runner_factory(rec))
    assert out["ok"] is True
    assert rec["argv"][0] == sys.executable
    assert "agentic_mcp.orchestrate" in rec["argv"]
    assert "--once" in rec["argv"]
    assert rec["cwd"] == proj
    expected_db = str(Path(proj) / ".agentic" / "graph.db")
    assert rec["env"]["AGENTIC_DB_PATH"] == expected_db


def test_spawn_tick_pattern_finder_maps_to_patterns(tmp_path):
    rec = {}
    tick_spawn.spawn_tick(str(tmp_path), "pattern_finder",
                          runner=_fake_runner_factory(rec))
    assert "agentic_mcp.patterns" in rec["argv"]


def test_spawn_tick_unknown_tick():
    out = tick_spawn.spawn_tick("C:/p", "nope", runner=None)
    assert out["ok"] is False
    assert "unknown tick" in out["error"]


def test_spawn_tick_runner_raises_is_caught(tmp_path):
    def boom(argv, cwd, env):
        raise RuntimeError("spawn failed")
    out = tick_spawn.spawn_tick(str(tmp_path), "orchestrate", runner=boom)
    assert out["ok"] is False
    assert "spawn failed" in out["error"]


def test_spawn_tick_nonzero_returncode(tmp_path):
    def runner(argv, cwd, env):
        class R:
            returncode = 1
            stdout = ""
            stderr = "traceback"
        return R()
    out = tick_spawn.spawn_tick(str(tmp_path), "orchestrate", runner=runner)
    assert out["ok"] is False
    assert "exit 1" in out["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_tick_spawn.py -v`
Expected: FAIL with "No module named 'agentic_mcp.tick_spawn'"

- [ ] **Step 3: Write the implementation**

Create `mcp-server/src/agentic_mcp/tick_spawn.py`:

```python
"""Spawn an existing stateless tick CLI as a short-lived subprocess.

The supervisor adds NOTHING to tick logic -- it shells out to the same module
CLIs a human would run (`python -m agentic_mcp.orchestrate --once`). The tick
operates on the project's own graph.db via the AGENTIC_DB_PATH env var. Only
EXISTING CLIs are mapped here; arch_review/promotion are added in later rungs
when their CLIs exist. Never raises: a spawn failure is an outcome dict, so a
crashing tick can never take the daemon down.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# tick name -> module CLI args (after `python -m`). Only ticks with a real
# `--once` CLI today. {repo} is filled with the project path at spawn time.
TICK_COMMANDS: dict[str, list[str]] = {
    "orchestrate": ["agentic_mcp.orchestrate", "--once", "--repo", "{repo}"],
    "pattern_finder": ["agentic_mcp.patterns", "--once", "--repo", "{repo}"],
}

_DEFAULT_TIMEOUT = 1800  # seconds; a hung tick is killed, not waited on forever


def _default_runner(argv, cwd, env):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=_DEFAULT_TIMEOUT)


def spawn_tick(project_path: str, tick: str, *, runner=None) -> dict:
    """Run one tick against project_path's graph.db. Returns an outcome dict;
    never raises. `runner(argv, cwd, env) -> CompletedProcess-like` is injectable
    so tests need no real subprocess."""
    if tick not in TICK_COMMANDS:
        return {"ok": False, "tick": tick, "error": f"unknown tick: {tick!r}"}
    runner = runner or _default_runner
    repo = str(project_path)
    argv = [sys.executable, "-m"] + [
        a.replace("{repo}", repo) for a in TICK_COMMANDS[tick]
    ]
    env = dict(os.environ)
    env["AGENTIC_DB_PATH"] = str(Path(repo) / ".agentic" / "graph.db")
    try:
        proc = runner(argv, repo, env)
    except Exception as e:  # noqa: BLE001 - spawn failure must never propagate
        return {"ok": False, "tick": tick, "error": str(e)}
    if getattr(proc, "returncode", 0) != 0:
        return {"ok": False, "tick": tick,
                "error": f"exit {proc.returncode}: {getattr(proc, 'stderr', '')[:500]}"}
    return {"ok": True, "tick": tick, "stdout": getattr(proc, "stdout", "")}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_tick_spawn.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/tick_spawn.py mcp-server/tests/test_tick_spawn.py
git commit -m "feat(supervisor): tick-name -> CLI spawner with injectable runner"
```

---

### Task 4: The scheduler pass (`supervisor.py` core)

**Goal:** A pure, stateless `scheduler_pass` that fires due ticks for enabled, non-paused projects and records state. Mirrors `orchestrate.tick`'s injectable-seam + never-raise shape.

**Files:**
- Create: `mcp-server/src/agentic_mcp/supervisor.py` (this task adds `scheduler_pass`; later tasks add the loop/CLI)
- Test: `mcp-server/tests/test_supervisor.py`

**Acceptance Criteria:**
- [ ] For each enabled, non-paused project, fires every due tick (`is_due` over its registry cadence + state last_run) and records run.
- [ ] Disabled (registry `enabled: false`) and runtime-paused projects are skipped.
- [ ] Not-yet-due ticks are skipped.
- [ ] `now` and `spawn_fn` are injectable; the pass never raises (a spawn outcome `ok:false` lands in `result["errors"]`, not an exception).

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_supervisor.py -q` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_supervisor.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor.py -v`
Expected: FAIL with "No module named 'agentic_mcp.supervisor'"

- [ ] **Step 3: Write the implementation**

Create `mcp-server/src/agentic_mcp/supervisor.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/supervisor.py mcp-server/tests/test_supervisor.py
git commit -m "feat(supervisor): pure never-raise scheduler_pass core"
```

---

### Task 5: Loopback control API (`control_api.py`)

**Goal:** A stdlib `http.server` on `127.0.0.1` exposing health, projects, run-now, and pause/resume. Bound to loopback only.

**Files:**
- Create: `mcp-server/src/agentic_mcp/control_api.py`
- Test: `mcp-server/tests/test_control_api.py`

**Acceptance Criteria:**
- [ ] `GET /health` -> `{"status":"ok","beat_at":...}`.
- [ ] `GET /projects` -> registry projects merged with state (last_run/outcome, paused).
- [ ] `POST /projects/{path}/pause` and `/resume` toggle the runtime pause flag.
- [ ] `POST /projects/{path}/run/{tick}` triggers a spawn (via an injected runner) and returns 202.
- [ ] Server binds `127.0.0.1` only.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_control_api.py -q` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_control_api.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_control_api.py -v`
Expected: FAIL with "No module named 'agentic_mcp.control_api'"

- [ ] **Step 3: Write the implementation**

Create `mcp-server/src/agentic_mcp/control_api.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_control_api.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/control_api.py mcp-server/tests/test_control_api.py
git commit -m "feat(supervisor): loopback http control+health API"
```

---

### Task 6: Daemon run loop + CLI + console script

**Goal:** Wire the scheduler pass, heartbeat, and control API into a `run_forever` loop with a `--once` mode; register the `agentic-supervisor` console script.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/supervisor.py` (add `run_once`, `run_forever`, `main`)
- Modify: `mcp-server/pyproject.toml` (console script)
- Test: `mcp-server/tests/test_supervisor_main.py`

**Acceptance Criteria:**
- [ ] `run_once(registry_path, state_path, now, spawn_fn)` opens state, runs one `scheduler_pass`, beats the heartbeat, returns the result.
- [ ] `main(["--once"])` runs one pass against the default/overridden registry + state and prints JSON, returns 0.
- [ ] `pyproject.toml` exposes `agentic-supervisor = "agentic_mcp.supervisor:main"`.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_main.py -q` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `mcp-server/tests/test_supervisor_main.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_main.py -v`
Expected: FAIL ("module 'agentic_mcp.supervisor' has no attribute 'run_once'")

- [ ] **Step 3: Write the implementation**

Append to `mcp-server/src/agentic_mcp/supervisor.py`:

```python
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
```

- [ ] **Step 4: Add the console script**

In `mcp-server/pyproject.toml`, under `[project.scripts]`, add the third line:

```toml
[project.scripts]
agentic-mcp = "agentic_mcp.server:main"
agentic-mcp-init = "agentic_mcp.init_project:cli"
agentic-supervisor = "agentic_mcp.supervisor:main"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor_main.py -q`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add mcp-server/src/agentic_mcp/supervisor.py mcp-server/pyproject.toml mcp-server/tests/test_supervisor_main.py
git commit -m "feat(supervisor): run_once/run_forever loop + agentic-supervisor CLI"
```

---

### Task 7: Windows keep-alive registration script

**Goal:** A PowerShell script that registers the supervisor with Task Scheduler (start at logon, restart on failure, periodic ensure-running), with a `-Print` dry-run that emits the command without executing.

**Files:**
- Create: `mcp-server/scripts/install-supervisor.ps1`
- Test: `mcp-server/tests/test_install_script.py`

**Acceptance Criteria:**
- [ ] The script is ASCII-only (PS 5.1 cp1252 gotcha).
- [ ] `-Print` emits the `schtasks`/`Register-ScheduledTask` intent without registering.
- [ ] Parse-checks clean via the PowerShell parser.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_install_script.py -q` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `mcp-server/tests/test_install_script.py`:

```python
from pathlib import Path


def _script() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "install-supervisor.ps1"


def test_install_script_exists():
    assert _script().exists()


def test_install_script_is_ascii():
    raw = _script().read_bytes()
    assert all(b < 128 for b in raw), "install-supervisor.ps1 must be ASCII-only"


def test_install_script_has_print_switch_and_task_name():
    text = _script().read_text(encoding="utf-8")
    assert "[switch]$Print" in text
    assert "AgenticSupervisor" in text
    assert "agentic-supervisor" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_install_script.py -v`
Expected: FAIL (script does not exist)

- [ ] **Step 3: Write the script**

Create `mcp-server/scripts/install-supervisor.ps1` (ASCII only — no smart quotes, em-dashes, or arrows in string literals):

```powershell
# Register the agentic supervisor with Windows Task Scheduler so it starts at
# logon and is restarted if it dies. Run with -Print to see the action without
# registering anything.
param(
    [switch]$Print
)

$ErrorActionPreference = "Stop"

$taskName = "AgenticSupervisor"
$exe = (Get-Command "agentic-supervisor" -ErrorAction SilentlyContinue).Source
if (-not $exe) {
    Write-Host "agentic-supervisor not found on PATH. Install the package first:"
    Write-Host "  pip install -e mcp-server"
    if (-not $Print) { exit 1 }
    $exe = "agentic-supervisor"
}

$action = New-ScheduledTaskAction -Execute $exe
$atLogon = New-ScheduledTaskTrigger -AtLogOn
# Ensure-running heartbeat: re-trigger every 5 minutes (no-op if already up).
$ensure = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable

if ($Print) {
    Write-Host "Would register scheduled task '$taskName':"
    Write-Host "  Execute : $exe"
    Write-Host "  Triggers: AtLogOn + every 5 minutes ensure-running"
    Write-Host "  Settings: RestartCount=3, RestartInterval=1m, StartWhenAvailable"
    exit 0
}

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger @($atLogon, $ensure) -Settings $settings -Force
Write-Host "Registered scheduled task '$taskName'."
```

- [ ] **Step 4: Parse-check the script (machine gotcha) and run tests**

Parse-check (per the global machine note — silently-broken hooks/scripts look identical to non-firing ones):

```powershell
$e = $null
[Management.Automation.Language.Parser]::ParseFile("mcp-server/scripts/install-supervisor.ps1", [ref]$null, [ref]$e); $e
```
Expected: no errors printed.

Run: `./.venv/Scripts/python.exe -m pytest tests/test_install_script.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add mcp-server/scripts/install-supervisor.ps1 mcp-server/tests/test_install_script.py
git commit -m "feat(supervisor): Windows Task Scheduler keep-alive install script"
```

---

### Task 8: Full-suite regression + example registry + docs note

**Goal:** Confirm the whole fast suite still passes with the new modules, and ship a documented example `registry.json` so a user can actually register this project.

**Files:**
- Create: `mcp-server/examples/registry.example.json`
- Modify: `docs/plans/HANDOFF.md` (append a short "always-on rung 0+1 landed" note — coordinate with existing edits)
- Test: full suite

**Acceptance Criteria:**
- [ ] `./.venv/Scripts/python.exe -m pytest -m "not llm" -q` passes (prior count + the new tests).
- [ ] An example registry exists showing this repo registered with `orchestrate`/`pattern_finder` cadences.

**Verify:** `./.venv/Scripts/python.exe -m pytest -m "not llm" -q` -> all pass

**Steps:**

- [ ] **Step 1: Create the example registry**

Create `mcp-server/examples/registry.example.json`:

```json
{
  "projects": [
    {
      "path": "D:/GitHub Projects/Studies/Superpowers Study",
      "enabled": true,
      "scope_mode": "isolated",
      "cadences": {
        "orchestrate": "2m",
        "pattern_finder": "6h"
      },
      "promotion_cap": 5
    }
  ]
}
```

- [ ] **Step 2: Smoke-test the daemon end to end (real subprocess, one pass)**

Copy the example to a temp registry pointing at this repo and run one real pass (this actually shells out to the orchestrate/patterns CLIs against this repo's graph.db):

```bash
AGENTIC_REGISTRY_PATH="mcp-server/examples/registry.example.json" \
AGENTIC_SUPERVISOR_DB="$TMP/agentic-super.db" \
./mcp-server/.venv/Scripts/python.exe -m agentic_mcp.supervisor --once
```
Expected: JSON with `fired`/`skipped`/`errors`. (On Windows PowerShell, set the env vars with `$env:` first.) Note: a real tick may legitimately be a no-op; a non-empty `errors` here is a finding to investigate, not necessarily a failure.

- [ ] **Step 3: Run the full fast suite**

Run (from `mcp-server/`): `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: PASS, with the new test files included (prior 199 + the new tests).

- [ ] **Step 4: Append the HANDOFF note**

Add a short bullet under current state in `docs/plans/HANDOFF.md` noting the always-on rung 0+1 (busy_timeout + supervisor) landed, the `agentic-supervisor --once` entry point, and that rungs 2-4 (HUD, gate, auto-rehydration) remain per the vision doc `docs/superpowers/specs/2026-05-25-always-on-companion-vision-design.md`.

- [ ] **Step 5: Commit**

```bash
git add mcp-server/examples/registry.example.json docs/plans/HANDOFF.md
git commit -m "chore(supervisor): example registry + HANDOFF note for rung 0+1"
```

---

## Self-Review

**Spec coverage (against the vision doc, Sections 1-2 + rung 0):**
- busy_timeout (rung 0) -> Task 0. [covered]
- Registry (`~/.agentic/registry.json`, per-project cadences) -> Task 1. [covered]
- Ephemeral state (`supervisor.db`, last_run/heartbeat, no durable data) -> Task 2. [covered]
- "Spawn existing ticks, add nothing to tick logic" -> Task 3 (only existing CLIs mapped). [covered]
- "Logic-free scheduler, never-raise, injectable seams" -> Task 4. [covered]
- Loopback control API (health/projects/run-now/pause-resume) -> Task 5. [covered]
- Daemon lifecycle + console script -> Task 6. [covered]
- Windows Task Scheduler keep-alive -> Task 7. [covered]
- Approve/decline/retry endpoints -> intentionally DEFERRED to rung 3 (G); noted in Task 5. [intentional gap]
- arch_review/promotion ticks -> DEFERRED (no CLIs yet); `TICK_COMMANDS` only maps existing CLIs, unknown ticks become a logged error (Task 4 test asserts this). [intentional gap]

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every verify step has an exact command + expected result.

**Type/name consistency:** `scheduler_pass(registry, state_conn, *, now, spawn_fn)` signature matches between Task 4 (definition) and Task 6 (caller via `run_once`). `spawn_tick(project_path, tick, *, runner)` consistent between Task 3 and its use in Tasks 5/6. `connect_state`, `record_run`, `get_last_run`, `beat`, `last_beat`, `set_paused`/`clear_paused`/`is_paused`, `all_state` used consistently across Tasks 2, 4, 5, 6. `load_registry`/`default_registry_path`/`parse_cadence`/`is_due` consistent across Tasks 1, 4, 6. `build_server(registry_loader, state_path, run_fn, port)` consistent between Task 5 and Task 6. Console script name `agentic-supervisor` consistent (Tasks 6, 7).

**Dependency order:** 0 standalone; 1/2/3 independent; 4 needs 1+2+3; 5 needs 2; 6 needs 4+5; 7 needs 6; 8 needs all.

---

## Notes for the implementer

- Run pytest FROM `mcp-server/` with `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`.
- No new runtime dependency: stdlib `http.server`, `subprocess`, `sqlite3`, `threading` only.
- ASCII-only in the `.ps1` string literals (Task 7); parse-check it before trusting it.
- Module style mirrors the codebase: `conn` first arg in state helpers; never-raise for the scheduler pass (a cron-driven surface); a direct misuse (bad registry at startup) MAY raise.
- The supervisor adds NOTHING to tick logic. If you find yourself importing `orchestrate`/`patterns` internals into the supervisor, stop — it shells out to their CLIs by design.

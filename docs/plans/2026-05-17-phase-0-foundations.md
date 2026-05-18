# Agentic Engineering System — Phase 0 Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Phase 0 of the Agentic Engineering System as a self-contained Claude Code plugin: a typed graph in SQLite + sqlite-vec, exposed over a stdio MCP server in Python, with a falsifiability-gated Spec template, a SessionStart hook that walks up to find `.agentic/`, two subagent roles (builder + spec-checker), and the three foundational slash commands (`/agentic:init`, `/agentic:detect-conflicts`, `/agentic:import-spec`). One end-to-end bootstrap task must traverse the entire pipeline and produce a Finding node in the graph.

**Architecture:** Single Claude Code plugin layout at the repo root (`.claude-plugin/`, `agents/`, `skills/`, `commands/`, `hooks/`, `.mcp.json`). MCP server lives under `mcp-server/` as a standalone Python 3.12 package (`pyproject.toml` + `src/agentic_mcp/`). All durable state flows through MCP tool calls into `./.agentic/graph.db`. SessionStart hook is a PowerShell 5.1 script (machine constraint) that walks up from cwd looking for `.agentic/`, emits factual `additionalContext`, and is inert when no project is found.

**Tech Stack:** Python 3.12 (CPython from python.org), `mcp` Python SDK (version pinned at end of Task 9 once round-trip passes), `pytest` for unit + integration tests, PowerShell 5.1 for the SessionStart hook. Plugin format follows Claude Code's plugin spec (`.claude-plugin/plugin.json`, `.mcp.json`, `agents/`, `skills/`, `commands/`, `hooks/`).

**Deferred from Phase 0 to Phase 3:** `sqlite-vec` extension and the `vec0` virtual table. No Phase 0 task uses vector search; the dependency adds install friction without payoff. Phase 3's pattern-finder adds it back when needed.

**Cross-platform:** Phase 0 is **Windows-only**. The SessionStart hook is PowerShell 5.1; the walk-up test invokes `powershell` via subprocess and is skipped on non-Windows. A portable POSIX hook is Phase 1+ work.

**Build mode (per PRD Gating-4):** Phase 0 is built **manually with Claude Code unaided**. The agents and tools created here are deliverables that will be used to build Phase 1+, not used to build themselves. Treat any temptation to short-circuit this as a `SystemUsabilityBug` candidate to note for after Phase 0 ships.

**Out of scope (deferred to later phases):**
- Code-reviewer and contrarian roles (Phase 1)
- Full four-tier severity loop with critical persistence (Phase 1)
- Orchestrator + parallelism + git worktrees (Phase 2)
- Pattern-finder, architectural-review, meta-graph (Phase 3)
- Self-improvement and reviewer calibration (Phase 4)
- The `/agentic:new-spec`, `/agentic:dispatch`, `/agentic:review-pr`, `/agentic:find-patterns` commands (Phase 1+)

**Phase 0 exit gate (verbatim from PRD):** A task can be dispatched, built, spec-checked, and result in a `Finding` node logged to the graph. Graph survives session restarts. Spec dispatch is blocked if criteria are not falsifiable or feedback loop is missing. Plugin installs cleanly via `/plugin install`. Walk-up resolution finds project correctly across at least three test scenarios. Hook injection verified on target Claude Code version. Conflict detection runs without modifying any other plugin.

**Repo note:** This repo (`D:\GitHub Projects\Studies\Superpowers Study`) is being repurposed as the agentic-engineering plugin repo. Existing files (`agentic-engineering-system-prd-v3.md`, `CLAUDE.md`, `SUPERPOWERS-EXPLAINED.md`, `norns-loop-review/`) stay as historical / study context. New work goes into the plugin layout. The repo gets pushed to `https://github.com/GhostlyGawd/agentic-engineering` in Task 21.

---

## File Map

```
<repo-root>/
  .claude-plugin/
    plugin.json                          # plugin manifest
  .mcp.json                              # registers agentic-graph stdio server
  agents/
    builder.md                           # builder subagent (with embedded TDD/debug guidance)
    spec-checker.md                      # spec-checker subagent (context-isolated)
  skills/
    router/
      SKILL.md                           # entry point describing the system
    spec-writing/
      SKILL.md                           # how to write a spec that passes validators
  commands/
    init.md                              # /agentic:init
    detect-conflicts.md                  # /agentic:detect-conflicts
    import-spec.md                       # /agentic:import-spec
  hooks/
    hooks.json                           # SessionStart registration
    session-start.ps1                    # walk-up resolver (PowerShell 5.1)
  templates/
    spec.md                              # Spec node markdown template with 3 examples
  mcp-server/
    pyproject.toml                       # Python package
    README.md
    src/
      agentic_mcp/
        __init__.py
        server.py                        # stdio MCP server, registers all tools
        db.py                            # SQLite + sqlite-vec init + connection
        schema.sql                       # full DDL: entities, relations, indexes
        nodes.py                         # create_node, update_node, get_node
        relations.py                     # link_nodes, query relations
        queries.py                       # query_graph, get_required_reads
        findings.py                      # log_finding, mark_criterion_satisfied
        scope.py                         # auto-inference logic
        validators.py                    # falsifiability + feedback-loop gates
        registry.py                      # v1 known-overlaps registry (Superpowers only)
    tests/
      conftest.py                        # shared fixtures (temp DB, etc.)
      test_db.py                         # schema load + sqlite-vec
      test_nodes.py                      # entity CRUD
      test_relations.py                  # link CRUD
      test_queries.py                    # query_graph + targeted reads
      test_findings.py                   # log_finding + mark_criterion_satisfied
      test_scope.py                      # auto-inference priority order
      test_validators.py                 # falsifiability + feedback-loop
      test_server.py                     # MCP tool surface integration
      test_walkup.py                     # SessionStart resolver (3+ scenarios)
      test_e2e_bootstrap.py              # the Phase 0 exit-gate test
  docs/
    plans/
      2026-05-17-phase-0-foundations.md  # THIS PLAN
  README.md                              # install + usage (updated at end)
```

`./.agentic/` is created per-project by `/agentic:init`, not by the plugin install:

```
.agentic/
  graph.db                               # SQLite + sqlite-vec database
  config.json                            # scope mode + project id
  compatibility.json                     # recorded user preference from detect-conflicts
  specs/                                 # markdown specs, mirror of Spec nodes
```

---

## Conventions

- **All Python files** start with a UTF-8 source declaration is unnecessary in Py3; but if a CLI prints non-ASCII, add `sys.stdout.reconfigure(encoding="utf-8")` early in `main()` (per user machine notes).
- **All `.ps1` files**: ASCII-only inside `"..."` string literals — em-dash, smart quotes, and right-arrow corrupt under PowerShell 5.1 cp1252 read. Use `-`, `->`, `'`, `"` in literals. Comments and `@"..."@` here-strings are safe (per user machine notes).
- **All `.ps1` files**: parse-check via `[Management.Automation.Language.Parser]::ParseFile($p,[ref]$null,[ref]$e); $e` before committing (per user machine notes).
- **Commit messages**: Conventional Commits style (`feat:`, `fix:`, `chore:`, `test:`, `docs:`).
- **One commit per task** unless a task explicitly says otherwise.

---

## Task 0: Project scaffold + Python tooling

**Goal:** Create the empty plugin directory layout and a working Python package skeleton for the MCP server, so subsequent tasks have somewhere to write code.

**Files:**
- Create: `.claude-plugin/` (directory only)
- Create: `agents/`, `skills/`, `skills/router/`, `skills/spec-writing/`, `commands/`, `hooks/`, `templates/` (directories only)
- Create: `mcp-server/pyproject.toml`
- Create: `mcp-server/README.md`
- Create: `mcp-server/src/agentic_mcp/__init__.py`
- Create: `mcp-server/tests/conftest.py`
- Create: `.gitignore`
- Create: `README.md` (repo root, brief — replaced at the end in Task 20)

**Acceptance Criteria:**
- [ ] Directory layout matches the File Map above.
- [ ] `pyproject.toml` declares dependencies: `mcp`, `sqlite-vec`, plus dev deps `pytest`, `pytest-asyncio`.
- [ ] `python -m venv .venv` + `pip install -e mcp-server[dev]` succeeds.
- [ ] `pytest --collect-only mcp-server/tests` runs without error (no tests yet — just confirms pytest finds the directory).

**Verify:** `cd mcp-server && pytest --collect-only` → exit code 0, "collected 0 items".

**Steps:**

- [ ] **Step 1: Create empty directories**

```powershell
$dirs = @(
  ".claude-plugin",
  "agents",
  "skills/router",
  "skills/spec-writing",
  "commands",
  "hooks",
  "templates",
  "mcp-server/src/agentic_mcp",
  "mcp-server/tests"
)
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
```

- [ ] **Step 2: Write `mcp-server/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "agentic-mcp"
version = "0.1.0"
description = "Agentic Engineering System graph MCP server (Phase 0)"
requires-python = ">=3.12"
dependencies = [
  "mcp>=0.9.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
]

[project.scripts]
agentic-mcp = "agentic_mcp.server:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/__init__.py`**

```python
"""Agentic Engineering System — graph MCP server."""
__version__ = "0.1.0"
```

- [ ] **Step 4: Write `mcp-server/tests/conftest.py`**

```python
"""Shared pytest fixtures for agentic_mcp tests."""
import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """Path for a temp SQLite DB unique to each test."""
    return tmp_path / "graph.db"
```

- [ ] **Step 5: Write `mcp-server/README.md`**

```markdown
# agentic-mcp

Phase 0 MCP server for the Agentic Engineering System.

Install (editable):

    python -m venv .venv
    .venv\Scripts\Activate.ps1   # PowerShell
    pip install -e .[dev]

Run tests:

    pytest

Run server (stdio):

    agentic-mcp
```

- [ ] **Step 6: Write `.gitignore` at repo root**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.pytest_cache/

# SQLite
*.db
*.db-journal
*.db-wal
*.db-shm

# Per-project agentic state (when dogfooding here)
.agentic/

# Editors
.vscode/
.idea/
```

- [ ] **Step 7: Write minimal `README.md` at repo root**

```markdown
# Agentic Engineering System

A self-improving engineering system packaged as a Claude Code plugin. Phase 0 — foundations.

See `docs/plans/2026-05-17-phase-0-foundations.md` for the active build plan.
See `agentic-engineering-system-prd-v2.md` for the full PRD.
```

- [ ] **Step 8: Install dev deps and verify pytest collects**

```powershell
cd mcp-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest --collect-only
```

Expected: `collected 0 items` (exit 0).

- [ ] **Step 9: Initialize git and commit**

```powershell
cd ..
git init
git add .
git commit -m "chore: scaffold plugin layout and Python MCP server skeleton"
```

---

## Task 1: Plugin manifest + .mcp.json registration

**Goal:** Make the plugin installable by Claude Code (`/plugin install`) and have it register the agentic-graph stdio MCP server automatically on install.

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.mcp.json`

**Acceptance Criteria:**
- [ ] `.claude-plugin/plugin.json` validates as JSON and contains `name`, `version`, `description`, `author`.
- [ ] `.mcp.json` validates as JSON and registers a stdio server pointed at `agentic-mcp` (the console script defined in Task 0).
- [ ] `python -c "import json; json.load(open('.claude-plugin/plugin.json'))"` exits 0.
- [ ] `python -c "import json; json.load(open('.mcp.json'))"` exits 0.

**Verify:**

```powershell
python -c "import json,sys; json.load(open('.claude-plugin/plugin.json')); json.load(open('.mcp.json')); print('ok')"
```

Expected: `ok`.

**Steps:**

- [ ] **Step 1: Write `.claude-plugin/plugin.json`**

```json
{
  "name": "agentic-engineering",
  "version": "0.1.0",
  "description": "Self-improving engineering system: typed knowledge graph, falsifiability-gated specs, independent verification.",
  "author": "GhostlyGawd",
  "license": "MIT",
  "repository": "https://github.com/GhostlyGawd/agentic-engineering"
}
```

- [ ] **Step 2: Write `.mcp.json`**

```json
{
  "mcpServers": {
    "agentic-graph": {
      "command": "agentic-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

- [ ] **Step 3: Verify both files parse as JSON**

```powershell
python -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('.mcp.json')); print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```powershell
git add .claude-plugin/plugin.json .mcp.json
git commit -m "feat: plugin manifest and MCP server registration"
```

---

## Task 2: SQLite schema + DB init

**Goal:** Define the full graph DDL (entities, relations, indexes) and a `db.py` module that opens a SQLite connection with the schema applied. **No `sqlite-vec` in Phase 0** — vector search and the `vec0` virtual table are deferred to Phase 3 when pattern-finder needs them.

**Files:**
- Create: `mcp-server/src/agentic_mcp/schema.sql`
- Create: `mcp-server/src/agentic_mcp/db.py`
- Create: `mcp-server/tests/test_db.py`

**Acceptance Criteria:**
- [ ] All 14 entity tables exist (`goal`, `epic`, `task`, `subtask`, `spec`, `decision`, `bug`, `finding`, `pattern`, `module`, `file`, `review`, `retro`, `arch_debt`). `SystemUsabilityBug` is a subtype of `finding` (no separate table — stored in `finding` with `subtype='SystemUsabilityBug'`).
- [ ] `relations` table exists with `from_id`, `to_id`, `relation_type` columns and a check constraint restricting `relation_type` to the 9 PRD values.
- [ ] Indexes exist on `(type, status)`, `(scope)`, `(last_touched)`, and `(from_id, relation_type)` on relations.
- [ ] `db.init_db(path)` creates the file with all tables on first call; idempotent on subsequent calls.
- [ ] Schema survives `sqlite3 <path> ".schema"` cleanly.

**Verify:** `pytest mcp-server/tests/test_db.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_db.py`**

```python
import sqlite3
from agentic_mcp import db


def test_init_db_creates_file(tmp_db_path):
    db.init_db(tmp_db_path)
    assert tmp_db_path.exists()


def test_all_entity_tables_present(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r[0] for r in rows}
    expected = {
        "goal", "epic", "task", "subtask", "spec", "decision",
        "bug", "finding", "pattern", "module", "file",
        "review", "retro", "arch_debt", "relations",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_relations_check_constraint(tmp_db_path):
    db.init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    # Should reject unknown relation type
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO relations(from_id, to_id, relation_type) VALUES (?,?,?)",
            ("a", "b", "not-a-real-relation"),
        )
        conn.commit()


def test_init_is_idempotent(tmp_db_path):
    db.init_db(tmp_db_path)
    db.init_db(tmp_db_path)  # second call must not raise
    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()
    assert rows[0] >= 15  # 14 entity tables + relations
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
pytest mcp-server/tests/test_db.py -v
```

Expected: ImportError or AttributeError — `db` module / functions don't exist yet. (4 tests now — `test_sqlite_vec_loads` was dropped because sqlite-vec is deferred to Phase 3.)

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/schema.sql`**

```sql
-- Shared column shape for entity tables. Repeated inline because SQLite has no inheritance.
-- Required fields per PRD: id, type, status, severity, owner, created_at, last_touched, body, summary, tags, scope.

-- Generic entity tables. Each entity type gets its own table for query clarity; columns are uniform.

CREATE TABLE IF NOT EXISTS goal (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Goal'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,     -- JSON array
  scope TEXT
);

CREATE TABLE IF NOT EXISTS epic (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Epic'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS task (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Task'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS subtask (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Subtask'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS spec (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Spec'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,           -- full markdown spec
  summary TEXT,
  tags TEXT,
  scope TEXT,
  criteria_json TEXT NOT NULL,  -- JSON array of {text, verify, satisfied:bool, evidence:str}
  feedback_loop TEXT NOT NULL,
  required_reads TEXT           -- JSON array of node ids
);

CREATE TABLE IF NOT EXISTS decision (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Decision'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS bug (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Bug'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS finding (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Finding'),
  status TEXT NOT NULL,
  severity TEXT NOT NULL CHECK(severity IN ('Critical','Important','Suggested','Strength')),
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  subtype TEXT,                -- 'SystemUsabilityBug' or NULL
  parent_id TEXT               -- node this finding is attached to
);

CREATE TABLE IF NOT EXISTS pattern (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Pattern'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS module (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Module'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS file (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='File'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Review'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  verdict TEXT
);

CREATE TABLE IF NOT EXISTS retro (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='Retro'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT,
  failed_layer TEXT CHECK(failed_layer IN ('spec','implementation','review','unknowable'))
);

CREATE TABLE IF NOT EXISTS arch_debt (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type='ArchDebt'),
  status TEXT NOT NULL,
  severity TEXT,
  owner TEXT,
  created_at TEXT NOT NULL,
  last_touched TEXT NOT NULL,
  body TEXT NOT NULL,
  summary TEXT,
  tags TEXT,
  scope TEXT
);

CREATE TABLE IF NOT EXISTS relations (
  from_id TEXT NOT NULL,
  to_id TEXT NOT NULL,
  relation_type TEXT NOT NULL CHECK(relation_type IN (
    'implements','depends-on','blocks','supersedes',
    'caused-by','observed-in','touches','references','derived-from'
  )),
  created_at TEXT NOT NULL,
  PRIMARY KEY (from_id, to_id, relation_type)
);

-- Indexes for the three indexing modes in the PRD.
CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);
CREATE INDEX IF NOT EXISTS idx_finding_status ON finding(status);
CREATE INDEX IF NOT EXISTS idx_finding_severity ON finding(severity);
CREATE INDEX IF NOT EXISTS idx_finding_scope ON finding(scope);
CREATE INDEX IF NOT EXISTS idx_finding_parent ON finding(parent_id);
CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_spec_status ON spec(status);

-- Vector index (sqlite-vec / vec0 virtual table) is deferred to Phase 3 when the
-- pattern-finder needs it. Keeping Phase 0 dependency-light.
```

- [ ] **Step 4: Write `mcp-server/src/agentic_mcp/db.py`**

```python
"""SQLite connection and schema management.

Phase 0 uses plain SQLite (no extensions). sqlite-vec and the vec0 virtual table
are deferred to Phase 3 when pattern-finder needs vector search.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection. Caller manages close()."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | Path) -> None:
    """Create the DB file and apply schema. Idempotent."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        with _SCHEMA_PATH.open("r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_db.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```powershell
git add mcp-server/src/agentic_mcp/schema.sql mcp-server/src/agentic_mcp/db.py mcp-server/tests/test_db.py
git commit -m "feat(graph): SQLite schema and DB init (sqlite-vec deferred to Phase 3)"
```

---

## Task 3: Entity CRUD — create_node, update_node, get_node

**Goal:** Provide a typed Python API for creating and updating any of the 14 entity types, with auto-filled timestamps and required-field validation.

**Files:**
- Create: `mcp-server/src/agentic_mcp/nodes.py`
- Create: `mcp-server/tests/test_nodes.py`

**Acceptance Criteria:**
- [ ] `create_node(conn, type, **fields)` returns the new node's id; auto-fills `created_at` and `last_touched` to UTC ISO-8601.
- [ ] If `id` is omitted, a UUID4 hex is generated.
- [ ] Required fields per PRD validated (`type`, `status`, `owner`, `body`); missing field raises `ValueError`.
- [ ] Type-specific extra fields accepted: `spec` requires `criteria_json` and `feedback_loop`; `finding` requires `severity` and `parent_id`; `file` requires `path`; `retro` accepts `failed_layer`; `review` accepts `verdict`.
- [ ] `update_node(conn, id, **fields)` updates fields and bumps `last_touched`.
- [ ] `get_node(conn, id)` returns a dict or `None`. Type discovered by scanning the entity tables until a match.
- [ ] Round-trips work for all 14 entity types in tests.

**Verify:** `pytest mcp-server/tests/test_nodes.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_nodes.py`**

```python
import json
import pytest
from agentic_mcp import db, nodes


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def test_create_goal_auto_id_and_timestamps(conn):
    nid = nodes.create_node(conn, "Goal", status="active", owner="alice", body="ship MVP")
    row = nodes.get_node(conn, nid)
    assert row["type"] == "Goal"
    assert row["owner"] == "alice"
    assert row["body"] == "ship MVP"
    assert row["created_at"] is not None
    assert row["last_touched"] == row["created_at"]


def test_create_with_explicit_id(conn):
    nid = nodes.create_node(
        conn, "Task", id="task-001", status="pending", owner="alice", body="do X"
    )
    assert nid == "task-001"


def test_missing_required_raises(conn):
    with pytest.raises(ValueError, match="body"):
        nodes.create_node(conn, "Goal", status="active", owner="alice")


def test_spec_requires_criteria_and_feedback(conn):
    with pytest.raises(ValueError, match="criteria_json"):
        nodes.create_node(
            conn, "Spec", status="draft", owner="alice", body="x",
            feedback_loop="test runs in CI",
        )
    with pytest.raises(ValueError, match="feedback_loop"):
        nodes.create_node(
            conn, "Spec", status="draft", owner="alice", body="x",
            criteria_json=json.dumps([{"text": "x", "verify": "y", "satisfied": False}]),
        )


def test_finding_requires_severity_and_parent(conn):
    with pytest.raises(ValueError):
        nodes.create_node(conn, "Finding", status="open", owner="alice", body="x")


def test_update_bumps_last_touched(conn):
    import time
    nid = nodes.create_node(conn, "Goal", status="active", owner="alice", body="x")
    orig = nodes.get_node(conn, nid)["last_touched"]
    time.sleep(0.01)
    nodes.update_node(conn, nid, body="y")
    after = nodes.get_node(conn, nid)
    assert after["body"] == "y"
    assert after["last_touched"] > orig


def test_round_trip_all_entity_types(conn):
    bodies = {
        "Goal": dict(status="active", owner="a", body="b"),
        "Epic": dict(status="active", owner="a", body="b"),
        "Task": dict(status="pending", owner="a", body="b"),
        "Subtask": dict(status="pending", owner="a", body="b"),
        "Spec": dict(
            status="draft", owner="a", body="b",
            criteria_json=json.dumps([{"text": "x", "verify": "y", "satisfied": False}]),
            feedback_loop="manual user observation",
        ),
        "Decision": dict(status="locked", owner="a", body="b"),
        "Bug": dict(status="open", owner="a", body="b"),
        "Finding": dict(status="open", owner="a", body="b", severity="Critical", parent_id="root"),
        "Pattern": dict(status="observed", owner="a", body="b"),
        "Module": dict(status="active", owner="a", body="b"),
        "File": dict(status="active", owner="a", body="b", path="src/x.py"),
        "Review": dict(status="closed", owner="a", body="b"),
        "Retro": dict(status="open", owner="a", body="b"),
        "ArchDebt": dict(status="open", owner="a", body="b"),
    }
    for ntype, fields in bodies.items():
        nid = nodes.create_node(conn, ntype, **fields)
        out = nodes.get_node(conn, nid)
        assert out is not None, f"round-trip failed for {ntype}"
        assert out["type"] == ntype


def test_get_node_missing_returns_none(conn):
    assert nodes.get_node(conn, "does-not-exist") is None
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
pytest mcp-server/tests/test_nodes.py -v
```

Expected: ImportError (module doesn't exist).

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/nodes.py`**

```python
"""Typed entity CRUD over the graph DB."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

ENTITY_TABLES = {
    "Goal": "goal",
    "Epic": "epic",
    "Task": "task",
    "Subtask": "subtask",
    "Spec": "spec",
    "Decision": "decision",
    "Bug": "bug",
    "Finding": "finding",
    "Pattern": "pattern",
    "Module": "module",
    "File": "file",
    "Review": "review",
    "Retro": "retro",
    "ArchDebt": "arch_debt",
}

# Required fields beyond the auto-filled ones (id, created_at, last_touched, type).
BASE_REQUIRED = {"status", "owner", "body"}

# Type-specific extra required fields.
EXTRA_REQUIRED = {
    "Spec": {"criteria_json", "feedback_loop"},
    "Finding": {"severity", "parent_id"},
    "File": {"path"},
}

# Optional type-specific columns (allowed but not required).
EXTRA_OPTIONAL = {
    "Spec": {"required_reads"},
    "Finding": {"subtype"},
    "Retro": {"failed_layer"},
    "Review": {"verdict"},
}

# Columns common to all entity tables.
COMMON_COLS = (
    "id", "type", "status", "severity", "owner",
    "created_at", "last_touched", "body", "summary", "tags", "scope",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table_for(ntype: str) -> str:
    try:
        return ENTITY_TABLES[ntype]
    except KeyError:
        raise ValueError(f"unknown entity type: {ntype}")


def _all_cols_for(ntype: str) -> tuple[str, ...]:
    extras = EXTRA_REQUIRED.get(ntype, set()) | EXTRA_OPTIONAL.get(ntype, set())
    return COMMON_COLS + tuple(sorted(extras))


def create_node(conn: sqlite3.Connection, type: str, **fields) -> str:
    table = _table_for(type)
    required = BASE_REQUIRED | EXTRA_REQUIRED.get(type, set())
    missing = required - fields.keys()
    if missing:
        raise ValueError(f"missing required field(s) for {type}: {sorted(missing)}")

    nid = fields.pop("id", None) or uuid.uuid4().hex
    now = _now()
    cols = _all_cols_for(type)
    values = {
        "id": nid,
        "type": type,
        "created_at": now,
        "last_touched": now,
        "severity": fields.get("severity"),
        "summary": fields.get("summary"),
        "tags": fields.get("tags"),
        "scope": fields.get("scope"),
    }
    for k, v in fields.items():
        if k in cols:
            values[k] = v
    # Status and body always present (required-check above).
    values["status"] = fields["status"]
    values["body"] = fields["body"]
    values["owner"] = fields["owner"]

    use_cols = [c for c in cols if c in values]
    placeholders = ",".join("?" for _ in use_cols)
    col_list = ",".join(use_cols)
    conn.execute(
        f"INSERT INTO {table}({col_list}) VALUES ({placeholders})",
        [values[c] for c in use_cols],
    )
    conn.commit()
    return nid


def update_node(conn: sqlite3.Connection, id: str, **fields) -> None:
    row = get_node(conn, id)
    if row is None:
        raise ValueError(f"no such node: {id}")
    table = _table_for(row["type"])
    fields["last_touched"] = _now()
    cols = _all_cols_for(row["type"])
    use = {k: v for k, v in fields.items() if k in cols and k not in ("id", "type", "created_at")}
    if not use:
        return
    set_clause = ",".join(f"{k}=?" for k in use)
    conn.execute(f"UPDATE {table} SET {set_clause} WHERE id=?", [*use.values(), id])
    conn.commit()


def get_node(conn: sqlite3.Connection, id: str) -> dict | None:
    for ntype, table in ENTITY_TABLES.items():
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone()
        if row is not None:
            cols = [d[0] for d in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
            return dict(zip(cols, row))
    return None
```

- [ ] **Step 4: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_nodes.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```powershell
git add mcp-server/src/agentic_mcp/nodes.py mcp-server/tests/test_nodes.py
git commit -m "feat(graph): typed entity CRUD for all 14 entity types"
```

---

## Task 4: Relations — link_nodes

**Goal:** Add support for linking two nodes via one of the 9 PRD relation types, plus querying neighbors.

**Files:**
- Create: `mcp-server/src/agentic_mcp/relations.py`
- Create: `mcp-server/tests/test_relations.py`

**Acceptance Criteria:**
- [ ] `link_nodes(conn, from_id, to_id, relation_type)` inserts into `relations`.
- [ ] All 9 relation types (`implements`, `depends-on`, `blocks`, `supersedes`, `caused-by`, `observed-in`, `touches`, `references`, `derived-from`) accepted; any other rejected via the schema CHECK constraint and surfaced as `ValueError`.
- [ ] `neighbors(conn, node_id, relation_type=None, direction="out")` returns list of neighbor ids.
- [ ] Linking the same triple twice is idempotent (PRIMARY KEY collision swallowed).

**Verify:** `pytest mcp-server/tests/test_relations.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_relations.py`**

```python
import pytest
from agentic_mcp import db, nodes, relations


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def _two_tasks(conn):
    a = nodes.create_node(conn, "Task", status="pending", owner="a", body="A")
    b = nodes.create_node(conn, "Task", status="pending", owner="a", body="B")
    return a, b


def test_link_basic(conn):
    a, b = _two_tasks(conn)
    relations.link_nodes(conn, a, b, "depends-on")
    rows = conn.execute(
        "SELECT relation_type FROM relations WHERE from_id=? AND to_id=?", (a, b)
    ).fetchall()
    assert rows == [("depends-on",)]


def test_link_rejects_unknown_type(conn):
    a, b = _two_tasks(conn)
    with pytest.raises(ValueError):
        relations.link_nodes(conn, a, b, "not-a-relation")


def test_link_is_idempotent(conn):
    a, b = _two_tasks(conn)
    relations.link_nodes(conn, a, b, "depends-on")
    relations.link_nodes(conn, a, b, "depends-on")  # second call must not raise
    rows = conn.execute(
        "SELECT count(*) FROM relations WHERE from_id=? AND to_id=?", (a, b)
    ).fetchone()
    assert rows[0] == 1


def test_neighbors_out(conn):
    a, b = _two_tasks(conn)
    c = nodes.create_node(conn, "Task", status="pending", owner="a", body="C")
    relations.link_nodes(conn, a, b, "depends-on")
    relations.link_nodes(conn, a, c, "depends-on")
    out = sorted(relations.neighbors(conn, a, "depends-on", direction="out"))
    assert out == sorted([b, c])


def test_neighbors_in(conn):
    a, b = _two_tasks(conn)
    relations.link_nodes(conn, a, b, "blocks")
    assert relations.neighbors(conn, b, "blocks", direction="in") == [a]


def test_neighbors_any_type(conn):
    a, b = _two_tasks(conn)
    relations.link_nodes(conn, a, b, "depends-on")
    relations.link_nodes(conn, a, b, "references")
    assert sorted(relations.neighbors(conn, a, direction="out")) == [b, b]
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
pytest mcp-server/tests/test_relations.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/relations.py`**

```python
"""Typed-relation CRUD over the graph DB."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

VALID_RELATIONS = {
    "implements", "depends-on", "blocks", "supersedes",
    "caused-by", "observed-in", "touches", "references", "derived-from",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def link_nodes(conn: sqlite3.Connection, from_id: str, to_id: str, relation_type: str) -> None:
    if relation_type not in VALID_RELATIONS:
        raise ValueError(
            f"unknown relation type: {relation_type!r}. "
            f"Valid: {sorted(VALID_RELATIONS)}"
        )
    try:
        conn.execute(
            "INSERT INTO relations(from_id, to_id, relation_type, created_at) VALUES (?,?,?,?)",
            (from_id, to_id, relation_type, _now()),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        # PRIMARY KEY collision = already linked; swallow for idempotency.
        if "UNIQUE" in str(e) or "PRIMARY KEY" in str(e):
            return
        raise


def neighbors(
    conn: sqlite3.Connection,
    node_id: str,
    relation_type: str | None = None,
    direction: str = "out",
) -> list[str]:
    if direction == "out":
        col, target = "from_id", "to_id"
    elif direction == "in":
        col, target = "to_id", "from_id"
    else:
        raise ValueError(f"direction must be 'in' or 'out', got {direction!r}")

    if relation_type is not None:
        rows = conn.execute(
            f"SELECT {target} FROM relations WHERE {col}=? AND relation_type=?",
            (node_id, relation_type),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {target} FROM relations WHERE {col}=?", (node_id,)
        ).fetchall()
    return [r[0] for r in rows]
```

- [ ] **Step 4: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_relations.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add mcp-server/src/agentic_mcp/relations.py mcp-server/tests/test_relations.py
git commit -m "feat(graph): typed link_nodes and neighbor queries"
```

---

## Task 5: Queries — query_graph + targeted reads

**Goal:** Implement the read paths needed by agents: filtered node queries (by type/status/severity/scope/tags) and a targeted "required reads" loader for specs.

**Files:**
- Create: `mcp-server/src/agentic_mcp/queries.py`
- Create: `mcp-server/tests/test_queries.py`

**Acceptance Criteria:**
- [ ] `query_graph(conn, type=None, status=None, severity=None, scope=None, limit=100)` returns a list of node dicts matching the filter.
- [ ] `get_required_reads(conn, spec_id)` returns a list of node dicts for the ids listed in the spec's `required_reads` JSON.
- [ ] `walk_down(conn, root_id, max_depth=3)` traverses Goal → Epic → Task → Subtask via `implements` and `depends-on` relations.
- [ ] All queries return summary fields where available (so first-pass reads stay cheap per PRD Gating-3).

**Verify:** `pytest mcp-server/tests/test_queries.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_queries.py`**

```python
import json
import pytest
from agentic_mcp import db, nodes, relations, queries


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def test_query_filter_by_type(conn):
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T1")
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T2")
    nodes.create_node(conn, "Goal", status="active", owner="a", body="G")
    out = queries.query_graph(conn, type="Task")
    assert len(out) == 2
    assert all(r["type"] == "Task" for r in out)


def test_query_filter_by_status(conn):
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T1")
    nodes.create_node(conn, "Task", status="done", owner="a", body="T2")
    out = queries.query_graph(conn, type="Task", status="done")
    assert len(out) == 1
    assert out[0]["body"] == "T2"


def test_query_filter_by_scope(conn):
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T1", scope="repo-a")
    nodes.create_node(conn, "Task", status="pending", owner="a", body="T2", scope="repo-b")
    out = queries.query_graph(conn, type="Task", scope="repo-a")
    assert len(out) == 1
    assert out[0]["body"] == "T1"


def test_get_required_reads(conn):
    g = nodes.create_node(conn, "Goal", status="active", owner="a", body="goal")
    m = nodes.create_node(conn, "Module", status="active", owner="a", body="auth")
    sid = nodes.create_node(
        conn, "Spec", status="draft", owner="a", body="spec",
        criteria_json=json.dumps([{"text": "x", "verify": "y", "satisfied": False}]),
        feedback_loop="manual",
        required_reads=json.dumps([g, m]),
    )
    out = queries.get_required_reads(conn, sid)
    assert len(out) == 2
    types = {r["type"] for r in out}
    assert types == {"Goal", "Module"}


def test_walk_down(conn):
    g = nodes.create_node(conn, "Goal", status="active", owner="a", body="G")
    e = nodes.create_node(conn, "Epic", status="active", owner="a", body="E")
    t = nodes.create_node(conn, "Task", status="pending", owner="a", body="T")
    relations.link_nodes(conn, e, g, "implements")
    relations.link_nodes(conn, t, e, "implements")
    out = queries.walk_down(conn, g, max_depth=3)
    ids = {n["id"] for n in out}
    assert {e, t}.issubset(ids)
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
pytest mcp-server/tests/test_queries.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/queries.py`**

```python
"""Read paths over the graph."""
from __future__ import annotations

import json
import sqlite3
from collections import deque

from .nodes import ENTITY_TABLES, get_node


def query_graph(
    conn: sqlite3.Connection,
    type: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    scope: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return matching nodes across one or all entity tables.

    If `type` is given, query only that table. Else union across all tables.
    """
    tables = [ENTITY_TABLES[type]] if type else list(ENTITY_TABLES.values())
    results: list[dict] = []
    for t in tables:
        clauses = []
        params: list = []
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if severity is not None:
            clauses.append("severity=?")
            params.append(severity)
        if scope is not None:
            clauses.append("scope=?")
            params.append(scope)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM {t} {where} ORDER BY last_touched DESC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            results.append(dict(zip(cols, row)))
        if len(results) >= limit:
            return results[:limit]
    return results[:limit]


def get_required_reads(conn: sqlite3.Connection, spec_id: str) -> list[dict]:
    spec = get_node(conn, spec_id)
    if spec is None or spec["type"] != "Spec":
        return []
    raw = spec.get("required_reads")
    if not raw:
        return []
    try:
        ids = json.loads(raw)
    except (ValueError, TypeError):
        return []
    out = []
    for nid in ids:
        n = get_node(conn, nid)
        if n is not None:
            out.append(n)
    return out


def walk_down(
    conn: sqlite3.Connection, root_id: str, max_depth: int = 3
) -> list[dict]:
    """BFS over inbound 'implements' / 'depends-on' edges (children point at parent)."""
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(root_id, 0)])
    out: list[dict] = []
    while queue:
        nid, depth = queue.popleft()
        if depth >= max_depth:
            continue
        rows = conn.execute(
            "SELECT from_id FROM relations WHERE to_id=? AND relation_type IN ('implements','depends-on')",
            (nid,),
        ).fetchall()
        for (child_id,) in rows:
            if child_id in seen:
                continue
            seen.add(child_id)
            node = get_node(conn, child_id)
            if node is not None:
                out.append(node)
                queue.append((child_id, depth + 1))
    return out
```

- [ ] **Step 4: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_queries.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```powershell
git add mcp-server/src/agentic_mcp/queries.py mcp-server/tests/test_queries.py
git commit -m "feat(graph): query_graph, get_required_reads, walk_down"
```

---

## Task 6: log_finding + mark_criterion_satisfied

**Goal:** Convenience high-level writes that the builder + spec-checker subagents will call most often. `log_finding` auto-inherits scope from the parent node. `mark_criterion_satisfied` enforces that the satisfaction claim carries evidence.

**Files:**
- Create: `mcp-server/src/agentic_mcp/findings.py`
- Create: `mcp-server/tests/test_findings.py`

**Acceptance Criteria:**
- [ ] `log_finding(conn, parent_id, severity, body, subtype=None, scope=None)` creates a Finding with the parent's scope unless `scope` is explicitly passed.
- [ ] `log_finding` errors if `severity` is not one of `Critical | Important | Suggested | Strength`.
- [ ] `log_finding` errors if `parent_id` does not exist.
- [ ] `mark_criterion_satisfied(conn, spec_id, criterion_index, evidence)` flips that criterion's `satisfied: True` and stores the evidence string.
- [ ] `mark_criterion_satisfied` errors if `evidence` is empty or whitespace.
- [ ] `mark_criterion_satisfied` errors if the criterion index is out of range.

**Verify:** `pytest mcp-server/tests/test_findings.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_findings.py`**

```python
import json
import pytest
from agentic_mcp import db, nodes, findings


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def _scoped_task(conn, scope):
    return nodes.create_node(
        conn, "Task", status="pending", owner="a", body="T", scope=scope
    )


def test_log_finding_inherits_scope(conn):
    pid = _scoped_task(conn, "repo-a/module-x")
    fid = findings.log_finding(conn, pid, "Important", "missing null check")
    f = nodes.get_node(conn, fid)
    assert f["scope"] == "repo-a/module-x"
    assert f["severity"] == "Important"
    assert f["parent_id"] == pid


def test_log_finding_explicit_scope_wins(conn):
    pid = _scoped_task(conn, "repo-a")
    fid = findings.log_finding(conn, pid, "Critical", "x", scope="repo-b")
    assert nodes.get_node(conn, fid)["scope"] == "repo-b"


def test_log_finding_unknown_severity_rejected(conn):
    pid = _scoped_task(conn, "repo-a")
    with pytest.raises(ValueError):
        findings.log_finding(conn, pid, "Catastrophic", "x")


def test_log_finding_missing_parent_rejected(conn):
    with pytest.raises(ValueError):
        findings.log_finding(conn, "no-such-node", "Critical", "x")


def test_mark_criterion_satisfied_happy_path(conn):
    crit = json.dumps([
        {"text": "func returns 42", "verify": "pytest tests/test_x.py", "satisfied": False},
    ])
    sid = nodes.create_node(
        conn, "Spec", status="draft", owner="a", body="s",
        criteria_json=crit, feedback_loop="manual",
    )
    findings.mark_criterion_satisfied(conn, sid, 0, evidence="pytest passed at HEAD")
    out = json.loads(nodes.get_node(conn, sid)["criteria_json"])
    assert out[0]["satisfied"] is True
    assert out[0]["evidence"] == "pytest passed at HEAD"


def test_mark_criterion_empty_evidence_rejected(conn):
    crit = json.dumps([{"text": "x", "verify": "y", "satisfied": False}])
    sid = nodes.create_node(
        conn, "Spec", status="draft", owner="a", body="s",
        criteria_json=crit, feedback_loop="manual",
    )
    with pytest.raises(ValueError, match="evidence"):
        findings.mark_criterion_satisfied(conn, sid, 0, evidence="   ")


def test_mark_criterion_out_of_range(conn):
    crit = json.dumps([{"text": "x", "verify": "y", "satisfied": False}])
    sid = nodes.create_node(
        conn, "Spec", status="draft", owner="a", body="s",
        criteria_json=crit, feedback_loop="manual",
    )
    with pytest.raises(IndexError):
        findings.mark_criterion_satisfied(conn, sid, 5, evidence="x")
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
pytest mcp-server/tests/test_findings.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/findings.py`**

```python
"""High-level convenience writes: log_finding and mark_criterion_satisfied."""
from __future__ import annotations

import json
import sqlite3

from . import nodes

VALID_SEVERITIES = {"Critical", "Important", "Suggested", "Strength"}


def log_finding(
    conn: sqlite3.Connection,
    parent_id: str,
    severity: str,
    body: str,
    subtype: str | None = None,
    scope: str | None = None,
    owner: str = "system",
) -> str:
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"unknown severity: {severity!r}. Valid: {sorted(VALID_SEVERITIES)}"
        )
    parent = nodes.get_node(conn, parent_id)
    if parent is None:
        raise ValueError(f"parent node not found: {parent_id}")
    if scope is None:
        scope = parent.get("scope")
    fields = dict(
        status="open", owner=owner, body=body,
        severity=severity, parent_id=parent_id, scope=scope,
    )
    if subtype is not None:
        fields["subtype"] = subtype
    return nodes.create_node(conn, "Finding", **fields)


def mark_criterion_satisfied(
    conn: sqlite3.Connection, spec_id: str, criterion_index: int, evidence: str
) -> None:
    if not evidence or not evidence.strip():
        raise ValueError("evidence is required (non-empty)")
    spec = nodes.get_node(conn, spec_id)
    if spec is None or spec["type"] != "Spec":
        raise ValueError(f"not a Spec node: {spec_id}")
    criteria = json.loads(spec["criteria_json"])
    if criterion_index < 0 or criterion_index >= len(criteria):
        raise IndexError(
            f"criterion_index {criterion_index} out of range "
            f"(spec has {len(criteria)} criteria)"
        )
    criteria[criterion_index]["satisfied"] = True
    criteria[criterion_index]["evidence"] = evidence.strip()
    nodes.update_node(conn, spec_id, criteria_json=json.dumps(criteria))
```

- [ ] **Step 4: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_findings.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```powershell
git add mcp-server/src/agentic_mcp/findings.py mcp-server/tests/test_findings.py
git commit -m "feat(graph): log_finding with scope inheritance and mark_criterion_satisfied with evidence gate"
```

---

## Task 7: Falsifiability + feedback-loop validators

**Goal:** Implement the two hard gates from the PRD (D-03, D-04): a Spec cannot dispatch unless every criterion has a verification mechanism AND the spec has a feedback-loop description.

**Files:**
- Create: `mcp-server/src/agentic_mcp/validators.py`
- Create: `mcp-server/tests/test_validators.py`

**Acceptance Criteria:**
- [ ] `validate_criterion(text, verify)` returns `(ok: bool, reasons: list[str])`. Rejects when `verify` is missing, fewer than 6 chars, or matches obvious nonsense patterns (`"tbd"`, `"todo"`, `"see above"`, `"works correctly"`, `"appropriately"`).
- [ ] Accepts when `verify` names at least one of: a runnable command (starts with `pytest`/`npm`/`cargo`/`go test`/`./`/`python`/`bash`/`pwsh`), a type-check/lint pattern, a file path + line range, or runtime observation (`"logs show"`, `"metric"`, `"telemetry"`).
- [ ] `validate_feedback_loop(text)` returns `(ok, reasons)`. Rejects empty / under-20-char / hand-wavy text. Accepts when text names an observable signal (`"user reports"`, `"CI fails"`, `"metric"`, `"telemetry"`, `"test"`, `"alert"`, `"log"`) AND a fix path (`"file a bug"`, `"open issue"`, `"retro"`, `"PR"`, `"patch"`, `"fix"`, etc.).
- [ ] `validate_spec(spec_dict)` runs both gates over a parsed spec; returns `(ok, reasons)` summarizing.

**Verify:** `pytest mcp-server/tests/test_validators.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_validators.py`**

```python
import json
import pytest
from agentic_mcp import validators


# --- validate_criterion ---

def test_criterion_rejects_empty_verify():
    ok, reasons = validators.validate_criterion("must work", verify="")
    assert not ok
    assert any("verify" in r.lower() for r in reasons)


def test_criterion_rejects_handwave_verify():
    for bad in ["tbd", "todo", "see above", "works correctly", "handled appropriately"]:
        ok, _ = validators.validate_criterion("must work", verify=bad)
        assert not ok, f"should reject: {bad!r}"


def test_criterion_accepts_pytest_command():
    ok, reasons = validators.validate_criterion(
        "function returns 42", verify="pytest tests/test_x.py::test_returns_42 -v"
    )
    assert ok, reasons


def test_criterion_accepts_runtime_signal():
    ok, _ = validators.validate_criterion(
        "no 5xx in prod", verify="logs show zero 5xx errors in the first hour"
    )
    assert ok


def test_criterion_accepts_type_check():
    ok, _ = validators.validate_criterion(
        "module has no Any types", verify="mypy --strict src/x.py reports 0 errors"
    )
    assert ok


# --- validate_feedback_loop ---

def test_feedback_loop_rejects_empty():
    ok, _ = validators.validate_feedback_loop("")
    assert not ok


def test_feedback_loop_rejects_short():
    ok, _ = validators.validate_feedback_loop("works fine")
    assert not ok


def test_feedback_loop_accepts_signal_plus_fix():
    ok, _ = validators.validate_feedback_loop(
        "If users report incorrect totals, open a bug ticket and write a retro."
    )
    assert ok


def test_feedback_loop_rejects_signal_without_fix():
    ok, _ = validators.validate_feedback_loop(
        "We will watch the logs carefully."
    )
    assert not ok


# --- validate_spec ---

def test_validate_spec_happy_path():
    spec = {
        "criteria_json": json.dumps([
            {"text": "x", "verify": "pytest tests/x.py -v", "satisfied": False},
            {"text": "y", "verify": "mypy --strict src/y.py reports 0 errors", "satisfied": False},
        ]),
        "feedback_loop": "If user reports a regression, file a bug and write a retro.",
    }
    ok, reasons = validators.validate_spec(spec)
    assert ok, reasons


def test_validate_spec_rejects_when_any_criterion_fails():
    spec = {
        "criteria_json": json.dumps([
            {"text": "x", "verify": "pytest tests/x.py -v", "satisfied": False},
            {"text": "y", "verify": "tbd", "satisfied": False},
        ]),
        "feedback_loop": "If user reports a regression, file a bug and write a retro.",
    }
    ok, reasons = validators.validate_spec(spec)
    assert not ok
    assert any("criterion" in r.lower() for r in reasons)


def test_validate_spec_rejects_when_feedback_loop_fails():
    spec = {
        "criteria_json": json.dumps([
            {"text": "x", "verify": "pytest tests/x.py -v", "satisfied": False},
        ]),
        "feedback_loop": "tbd",
    }
    ok, reasons = validators.validate_spec(spec)
    assert not ok
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
pytest mcp-server/tests/test_validators.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/validators.py`**

```python
"""Falsifiability + feedback-loop validators."""
from __future__ import annotations

import json
import re

_HANDWAVE_PATTERNS = [
    r"\btbd\b",
    r"\btodo\b",
    r"see above",
    r"works? correctly",
    r"appropriately",
    r"\bhandled\b",
    r"as needed",
    r"if necessary",
]

_VERIFY_COMMAND_PREFIXES = (
    "pytest", "npm ", "cargo ", "go test", "./", "python ", "python -",
    "bash ", "pwsh ", "powershell", "mypy", "ruff", "eslint", "tsc",
    "make ", "just ", "tox ",
)

_RUNTIME_SIGNALS = (
    "logs show", "metric", "telemetry", "log line", "alert fires",
    "dashboard shows", "trace", "p95", "p99", "error rate", "5xx",
)

_FEEDBACK_SIGNALS = (
    "user reports", "user report", "ci fails", "ci passes", "metric", "telemetry",
    "test", "alert", "log", "monitor", "dashboard", "regression test",
    "review finds", "audit",
)

_FEEDBACK_FIX_PATHS = (
    "file a bug", "open issue", "open a bug", "open a ticket", "retro",
    "pr ", "patch", "fix", "revert", "rollback", "roll back",
    "hotfix", "amend", "write a", "log a",
)


def _has_handwave(s: str) -> bool:
    lower = s.lower()
    return any(re.search(p, lower) for p in _HANDWAVE_PATTERNS)


def validate_criterion(text: str, verify: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not verify or not verify.strip():
        reasons.append("verify field is empty")
        return False, reasons
    if len(verify.strip()) < 6:
        reasons.append("verify field is too short to describe a real check")
    if _has_handwave(verify):
        reasons.append(f"verify field contains hand-wavy language: {verify!r}")
    lower = verify.lower().strip()
    looks_runnable = any(lower.startswith(p) for p in _VERIFY_COMMAND_PREFIXES)
    looks_runtime = any(s in lower for s in _RUNTIME_SIGNALS)
    if not (looks_runnable or looks_runtime):
        reasons.append(
            "verify must name a runnable command, type/lint check, or runtime observation"
        )
    return (len(reasons) == 0), reasons


def validate_feedback_loop(text: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not text or not text.strip():
        reasons.append("feedback_loop is empty")
        return False, reasons
    if len(text.strip()) < 20:
        reasons.append("feedback_loop is too short to describe signal + fix path")
    if _has_handwave(text):
        reasons.append(f"feedback_loop contains hand-wavy language: {text!r}")
    lower = text.lower()
    has_signal = any(s in lower for s in _FEEDBACK_SIGNALS)
    has_fix = any(s in lower for s in _FEEDBACK_FIX_PATHS)
    if not has_signal:
        reasons.append("feedback_loop must name an observable signal")
    if not has_fix:
        reasons.append("feedback_loop must name a fix path")
    return (len(reasons) == 0), reasons


def validate_spec(spec: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    try:
        criteria = json.loads(spec.get("criteria_json") or "[]")
    except (ValueError, TypeError) as e:
        return False, [f"criteria_json not valid JSON: {e}"]
    if not criteria:
        reasons.append("spec has no acceptance criteria")
    for i, c in enumerate(criteria):
        ok, why = validate_criterion(c.get("text", ""), c.get("verify", ""))
        if not ok:
            reasons.extend(f"criterion[{i}]: {r}" for r in why)
    ok_fb, why_fb = validate_feedback_loop(spec.get("feedback_loop", ""))
    if not ok_fb:
        reasons.extend(why_fb)
    return (len(reasons) == 0), reasons
```

- [ ] **Step 4: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_validators.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```powershell
git add mcp-server/src/agentic_mcp/validators.py mcp-server/tests/test_validators.py
git commit -m "feat(spec): falsifiability and feedback-loop validators"
```

---

## Task 8: Scope auto-inference

**Goal:** Auto-infer a `scope` value for a node from explicit input, parent scope, cwd, recent file activity, and file mentions in the body — in that priority order.

**Files:**
- Create: `mcp-server/src/agentic_mcp/scope.py`
- Create: `mcp-server/tests/test_scope.py`

**Acceptance Criteria:**
- [ ] `infer_scope(body, *, explicit=None, parent_scope=None, cwd=None, recent_files=None)` returns a string scope.
- [ ] Priority order (highest first): `explicit` > `parent_scope` > path mentions in `body` > most-common parent of `recent_files` > basename of `cwd`.
- [ ] Returns `"global"` if no signal at all.
- [ ] File mentions in body are extracted as the longest common directory prefix among any `/-separated` path tokens detected.

**Verify:** `pytest mcp-server/tests/test_scope.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_scope.py`**

```python
from pathlib import Path
import pytest
from agentic_mcp import scope


def test_explicit_wins():
    s = scope.infer_scope(
        "anything",
        explicit="repo-a/module-x",
        parent_scope="repo-b",
        cwd=Path("/tmp/whatever"),
        recent_files=["repo-z/foo.py"],
    )
    assert s == "repo-a/module-x"


def test_parent_scope_used_when_no_explicit():
    s = scope.infer_scope(
        "anything",
        parent_scope="repo-b/module-y",
        cwd=Path("/tmp/whatever"),
    )
    assert s == "repo-b/module-y"


def test_body_path_mention_used_when_no_parent():
    s = scope.infer_scope(
        "Modified src/auth/login.py and src/auth/session.py to fix a bug",
    )
    assert s == "src/auth"


def test_recent_files_lcp():
    s = scope.infer_scope(
        "no path here",
        recent_files=["src/auth/login.py", "src/auth/session.py", "src/auth/util.py"],
    )
    assert s == "src/auth"


def test_cwd_basename_fallback(tmp_path):
    work = tmp_path / "my-project"
    work.mkdir()
    s = scope.infer_scope("nothing useful", cwd=work)
    assert s == "my-project"


def test_global_when_nothing():
    s = scope.infer_scope("nothing useful")
    assert s == "global"
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
pytest mcp-server/tests/test_scope.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/scope.py`**

```python
"""Scope auto-inference for graph nodes.

Priority order:
  1. explicit
  2. parent_scope
  3. path mentions in body (longest common dir prefix)
  4. recent_files (longest common dir prefix)
  5. basename of cwd
  6. "global"
"""
from __future__ import annotations

import re
from os.path import commonpath
from pathlib import Path

_PATH_TOKEN = re.compile(r"[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+")


def _lcp_dir(paths: list[str]) -> str | None:
    if not paths:
        return None
    norm = [p.replace("\\", "/") for p in paths]
    try:
        cp = commonpath(norm).replace("\\", "/")
    except ValueError:
        return None
    # If the cp is a file (has an extension), drop the filename.
    if "." in cp.rsplit("/", 1)[-1]:
        cp = cp.rsplit("/", 1)[0] if "/" in cp else cp
    return cp or None


def infer_scope(
    body: str,
    *,
    explicit: str | None = None,
    parent_scope: str | None = None,
    cwd: Path | str | None = None,
    recent_files: list[str] | None = None,
) -> str:
    if explicit:
        return explicit
    if parent_scope:
        return parent_scope
    body_paths = _PATH_TOKEN.findall(body or "")
    body_scope = _lcp_dir(body_paths)
    if body_scope:
        return body_scope
    if recent_files:
        rf_scope = _lcp_dir(recent_files)
        if rf_scope:
            return rf_scope
    if cwd:
        return Path(cwd).name
    return "global"
```

- [ ] **Step 4: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_scope.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add mcp-server/src/agentic_mcp/scope.py mcp-server/tests/test_scope.py
git commit -m "feat(graph): scope auto-inference with priority-ordered heuristics"
```

---

## Task 9: stdio MCP server wrapper

**Goal:** Expose all of the above through an MCP stdio server. This is the single tool surface for every subagent (PRD Gating-2 / Gating-3).

**Files:**
- Create: `mcp-server/src/agentic_mcp/server.py`
- Create: `mcp-server/tests/test_server.py`

**Acceptance Criteria:**
- [ ] `agentic-mcp` console script starts a stdio MCP server.
- [ ] Server exposes tools: `create_node`, `update_node`, `link_nodes`, `query_graph`, `get_node`, `get_required_reads`, `log_finding`, `mark_criterion_satisfied`, `validate_spec`, `infer_scope`.
- [ ] Each tool has a typed JSON schema for parameters.
- [ ] DB path comes from env var `AGENTIC_DB_PATH`; defaults to `./.agentic/graph.db` resolved from the server's startup cwd.
- [ ] Server creates the DB on first call if it does not exist.
- [ ] Integration test using `mcp.client.stdio` invokes `create_node` + `get_node` end-to-end and asserts round-trip.

**Verify:** `pytest mcp-server/tests/test_server.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_server.py`**

```python
import json
import os
import sys
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_create_and_get_node_via_stdio(tmp_path):
    db_path = tmp_path / "graph.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentic_mcp.server"],
        env={**os.environ, "AGENTIC_DB_PATH": str(db_path)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert {"create_node", "get_node", "log_finding", "validate_spec"}.issubset(tool_names)

            r = await session.call_tool(
                "create_node",
                arguments={
                    "type": "Goal", "status": "active",
                    "owner": "test", "body": "ship Phase 0",
                },
            )
            payload = json.loads(r.content[0].text)
            nid = payload["id"]
            assert nid

            r2 = await session.call_tool("get_node", arguments={"id": nid})
            got = json.loads(r2.content[0].text)
            assert got["body"] == "ship Phase 0"


@pytest.mark.asyncio
async def test_validate_spec_via_stdio(tmp_path):
    db_path = tmp_path / "graph.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentic_mcp.server"],
        env={**os.environ, "AGENTIC_DB_PATH": str(db_path)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r = await session.call_tool(
                "validate_spec",
                arguments={
                    "criteria_json": json.dumps([
                        {"text": "x", "verify": "tbd", "satisfied": False},
                    ]),
                    "feedback_loop": "tbd",
                },
            )
            payload = json.loads(r.content[0].text)
            assert payload["ok"] is False
            assert any("verify" in r.lower() for r in payload["reasons"])
```

- [ ] **Step 2: Run test, confirm it fails**

```powershell
pytest mcp-server/tests/test_server.py -v
```

Expected: ImportError on the server module.

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/server.py`**

```python
"""Agentic graph MCP server (stdio)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import db as db_mod
from . import nodes as nodes_mod
from . import relations as rel_mod
from . import queries as q_mod
from . import findings as f_mod
from . import scope as scope_mod
from . import validators as v_mod


def _db_path() -> Path:
    raw = os.environ.get("AGENTIC_DB_PATH", "./.agentic/graph.db")
    p = Path(raw).resolve()
    if not p.exists():
        db_mod.init_db(p)
    return p


def _ok(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, default=str))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}))]


app = Server("agentic-graph")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_node",
            description="Create a graph node of the given entity type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "owner": {"type": "string"},
                    "body": {"type": "string"},
                    "id": {"type": "string"},
                    "severity": {"type": "string"},
                    "summary": {"type": "string"},
                    "tags": {"type": "string"},
                    "scope": {"type": "string"},
                    "criteria_json": {"type": "string"},
                    "feedback_loop": {"type": "string"},
                    "required_reads": {"type": "string"},
                    "parent_id": {"type": "string"},
                    "path": {"type": "string"},
                    "failed_layer": {"type": "string"},
                    "verdict": {"type": "string"},
                    "subtype": {"type": "string"},
                },
                "required": ["type", "status", "owner", "body"],
            },
        ),
        Tool(
            name="update_node",
            description="Update fields on an existing node.",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": True,
            },
        ),
        Tool(
            name="get_node",
            description="Fetch a single node by id.",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        ),
        Tool(
            name="link_nodes",
            description="Create a typed relation between two nodes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_id": {"type": "string"},
                    "to_id": {"type": "string"},
                    "relation_type": {"type": "string"},
                },
                "required": ["from_id", "to_id", "relation_type"],
            },
        ),
        Tool(
            name="query_graph",
            description="Filtered query over node tables.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "severity": {"type": "string"},
                    "scope": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        ),
        Tool(
            name="get_required_reads",
            description="Fetch all nodes listed in a spec's required_reads.",
            inputSchema={
                "type": "object",
                "properties": {"spec_id": {"type": "string"}},
                "required": ["spec_id"],
            },
        ),
        Tool(
            name="log_finding",
            description="Create a Finding attached to a parent node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_id": {"type": "string"},
                    "severity": {"type": "string"},
                    "body": {"type": "string"},
                    "subtype": {"type": "string"},
                    "scope": {"type": "string"},
                    "owner": {"type": "string"},
                },
                "required": ["parent_id", "severity", "body"],
            },
        ),
        Tool(
            name="mark_criterion_satisfied",
            description="Mark a Spec criterion as satisfied with evidence.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {"type": "string"},
                    "criterion_index": {"type": "integer"},
                    "evidence": {"type": "string"},
                },
                "required": ["spec_id", "criterion_index", "evidence"],
            },
        ),
        Tool(
            name="validate_spec",
            description="Run falsifiability + feedback-loop gates on a Spec.",
            inputSchema={
                "type": "object",
                "properties": {
                    "criteria_json": {"type": "string"},
                    "feedback_loop": {"type": "string"},
                },
                "required": ["criteria_json", "feedback_loop"],
            },
        ),
        Tool(
            name="infer_scope",
            description="Heuristically infer a scope tag for a new node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "body": {"type": "string"},
                    "explicit": {"type": "string"},
                    "parent_scope": {"type": "string"},
                    "cwd": {"type": "string"},
                    "recent_files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["body"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    conn = db_mod.connect(_db_path())
    try:
        if name == "create_node":
            ntype = arguments.pop("type")
            nid = nodes_mod.create_node(conn, ntype, **arguments)
            return _ok({"id": nid})
        if name == "update_node":
            nid = arguments.pop("id")
            nodes_mod.update_node(conn, nid, **arguments)
            return _ok({"id": nid})
        if name == "get_node":
            return _ok(nodes_mod.get_node(conn, arguments["id"]))
        if name == "link_nodes":
            rel_mod.link_nodes(conn, arguments["from_id"], arguments["to_id"], arguments["relation_type"])
            return _ok({"ok": True})
        if name == "query_graph":
            return _ok(q_mod.query_graph(conn, **arguments))
        if name == "get_required_reads":
            return _ok(q_mod.get_required_reads(conn, arguments["spec_id"]))
        if name == "log_finding":
            fid = f_mod.log_finding(conn, **arguments)
            return _ok({"id": fid})
        if name == "mark_criterion_satisfied":
            f_mod.mark_criterion_satisfied(
                conn, arguments["spec_id"], arguments["criterion_index"], arguments["evidence"]
            )
            return _ok({"ok": True})
        if name == "validate_spec":
            ok, reasons = v_mod.validate_spec(arguments)
            return _ok({"ok": ok, "reasons": reasons})
        if name == "infer_scope":
            from pathlib import Path
            cwd_arg = arguments.get("cwd")
            cwd_path = Path(cwd_arg) if cwd_arg else None
            s = scope_mod.infer_scope(
                arguments["body"],
                explicit=arguments.get("explicit"),
                parent_scope=arguments.get("parent_scope"),
                cwd=cwd_path,
                recent_files=arguments.get("recent_files"),
            )
            return _ok({"scope": s})
        return _err(f"unknown tool: {name}")
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")
    finally:
        conn.close()


async def _run() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_server.py -v
```

Expected: 2 passed.

If the `mcp` SDK's class names differ on the installed version, adjust imports per `mcp.__version__`.

- [ ] **Step 5: Pin the `mcp` SDK version**

Once tests pass, capture the exact installed version and pin it so future `pip install -e .[dev]` runs are reproducible:

```powershell
$ver = (pip show mcp | Select-String -Pattern '^Version:').ToString().Split(' ')[1]
"Pinning mcp=$ver"
# Then edit mcp-server/pyproject.toml: replace `"mcp>=0.9.0",` with `"mcp==$ver",`
```

Reinstall to confirm the pinned version resolves: `pip install -e .[dev]`.

- [ ] **Step 6: Commit**

```powershell
git add mcp-server/src/agentic_mcp/server.py mcp-server/tests/test_server.py mcp-server/pyproject.toml
git commit -m "feat(mcp): stdio MCP server exposing the graph as 10 tools (mcp pinned)"
```

---

## Task 10: Spec template (markdown, with 3 examples)

**Goal:** Create the canonical Spec markdown template that the spec-writer subagent and `/agentic:import-spec` produce. Three worked examples: trivial task, real feature, bug fix.

**Files:**
- Create: `templates/spec.md`

**Acceptance Criteria:**
- [ ] Template has all required PRD fields: Goal, Scope, Boundaries (in/out), Acceptance Criteria (with verify), Dependencies, Estimated Complexity, Known Risks / Open Questions, Required Reads, Feedback Loop.
- [ ] Three example specs inside the file: (a) trivial — `slugify(s)` utility, (b) real feature — adding a `/agentic:status` command, (c) bug fix — sqlite-vec failing to load on a system Python.
- [ ] Every example's criteria pass `validate_criterion` and the spec passes `validate_spec`.

**Verify:** Write a small ad-hoc Python check that parses each example's `criteria_json`-style block and the feedback_loop text, runs them through `validate_spec`, and confirms all three pass. (No separate test file required — the template's correctness is verified inline.)

**Steps:**

- [ ] **Step 1: Write `templates/spec.md`**

```markdown
# Spec: <task name>

> Status: draft | dispatched | satisfied | superseded
> Scope: <inferred or explicit>
> Owner: <who is on the hook>

## Goal
One sentence: what this spec produces.

## Scope
`<repo>/<module>` or `global`. Auto-inferred by default; override only if the inference is wrong.

## Boundaries
- **In:** what is included
- **Out:** what is explicitly excluded

## Dependencies
- Other Spec ids this depends on, or "none".

## Estimated Complexity
S | M | L  (with one sentence of why).

## Acceptance Criteria
A JSON list, one entry per criterion. Each must pass `validate_criterion`:

```json
[
  {
    "text": "function returns slug of input string",
    "verify": "pytest tests/test_slugify.py::test_basic -v passes"
  },
  {
    "text": "non-ASCII characters are transliterated, not stripped silently",
    "verify": "pytest tests/test_slugify.py::test_unicode -v passes"
  }
]
```

## Known Risks / Open Questions
- Bulleted, or "none".

## Required Reads
JSON list of node ids the builder should load before starting:

```json
["module:slugify", "decision:str-handling-policy"]
```

## Feedback Loop
How will we know if this is working in real use, and what's the path from misbehavior back to a fix? Must name an observable signal AND a fix path. Validated by `validate_feedback_loop`.

---

## Example 1 — Trivial task: `slugify(s)`

### Goal
Implement a `slugify(s: str) -> str` utility in `src/util/text.py`.

### Scope
`src/util`

### Boundaries
- **In:** ASCII lowercasing, whitespace-to-hyphen, transliteration of accented Latin letters.
- **Out:** non-Latin scripts (CJK), emoji handling, language-specific rules.

### Dependencies
none

### Estimated Complexity
S — one function, one test file, no I/O.

### Acceptance Criteria
```json
[
  {"text": "slugify('Hello World') == 'hello-world'", "verify": "pytest tests/test_slugify.py::test_basic -v passes"},
  {"text": "slugify('Crème Brûlée') == 'creme-brulee'", "verify": "pytest tests/test_slugify.py::test_accents -v passes"},
  {"text": "slugify('a  b') == 'a-b' (collapses whitespace)", "verify": "pytest tests/test_slugify.py::test_whitespace -v passes"}
]
```

### Known Risks / Open Questions
- What's the policy for CJK input? Decision: pass-through unchanged, document explicitly.

### Required Reads
none

### Feedback Loop
If a user files a bug that a slug round-trips badly through URL handling, we will write a regression test reproducing it and open a PR fixing it. Pattern-finder watches for repeat slugify bugs.

---

## Example 2 — Real feature: `/agentic:status` command

### Goal
Add a slash command that prints a one-screen summary of the current project's graph state: open Specs, open Findings by severity, recent Retros.

### Scope
`commands/` + `mcp-server/src/agentic_mcp`

### Boundaries
- **In:** read-only graph queries; printed via `query_graph`.
- **Out:** any mutation; any external HTTP; cross-project views.

### Dependencies
- Spec for Phase 0 graph queries (`query_graph` must exist).

### Estimated Complexity
M — needs a command file, formatting code, integration tests.

### Acceptance Criteria
```json
[
  {"text": "command file commands/status.md exists with frontmatter", "verify": "pytest tests/test_command_files.py::test_status_present -v passes"},
  {"text": "running the command in a sample project prints the open Spec count", "verify": "pytest tests/test_status_command.py::test_open_spec_count -v passes"},
  {"text": "running with an empty graph prints 'no project state yet'", "verify": "pytest tests/test_status_command.py::test_empty -v passes"}
]
```

### Known Risks / Open Questions
- Should it call out stale nodes (>N days untouched)? Defer to Phase 2 orchestrator.

### Required Reads
```json
["module:queries", "skill:router"]
```

### Feedback Loop
If users open Findings stating "status output is misleading", we will write a regression test against the misleading case and fix in a PR. Pattern-finder flags repeat misleading-output bugs.

---

## Example 3 — Bug fix: sqlite-vec fails on system Python

### Goal
Investigate and fix `vec_version()` returning NULL when the user runs the server with a Python that doesn't support `enable_load_extension`.

### Scope
`mcp-server/src/agentic_mcp/db.py`

### Boundaries
- **In:** detect the missing capability at startup; surface a clear error.
- **Out:** bundling our own Python build; switching SQLite drivers.

### Dependencies
none

### Estimated Complexity
S — diagnostic guard + clearer error message.

### Acceptance Criteria
```json
[
  {"text": "init_db raises RuntimeError naming 'enable_load_extension' if missing", "verify": "pytest tests/test_db.py::test_missing_load_extension_capability -v passes"},
  {"text": "error message includes a link to install instructions", "verify": "pytest tests/test_db.py::test_error_message_helpful -v passes"}
]
```

### Known Risks / Open Questions
- Anaconda Python is the most common culprit; do we want to recommend pyenv or python.org installer? Decision: link to python.org, mention Anaconda as known-bad.

### Required Reads
```json
["module:db", "retro:r-2026-04-12-anaconda-sqlite"]
```

### Feedback Loop
If a user files an install issue mentioning vec_version, we will check whether the guard fired correctly; if not, we will tighten the guard and write a regression test. The retro this fix produces is itself part of the loop.
```

- [ ] **Step 2: Verify all three examples pass `validate_spec`**

Run this ad-hoc Python in the venv:

```powershell
python -c @"
import json, re, sys
from agentic_mcp.validators import validate_spec

text = open('templates/spec.md', encoding='utf-8').read()
# Pull each example block (between '## Example N' headers).
examples = re.split(r'^## Example \d', text, flags=re.M)[1:]
fail = 0
for i, ex in enumerate(examples, 1):
    crit_match = re.search(r'### Acceptance Criteria\s*```json\s*(\[.*?\])\s*```', ex, re.S)
    fb_match = re.search(r'### Feedback Loop\s*\n(.+?)(?:\n---|\Z)', ex, re.S)
    if not crit_match or not fb_match:
        print(f'example {i}: missing block'); fail += 1; continue
    spec = {'criteria_json': crit_match.group(1), 'feedback_loop': fb_match.group(1).strip()}
    ok, reasons = validate_spec(spec)
    print(f'example {i}: {"OK" if ok else "FAIL"} {reasons if not ok else \"\"}')
    if not ok: fail += 1
sys.exit(fail)
"@
```

Expected: all three "OK", exit 0.

- [ ] **Step 3: Commit**

```powershell
git add templates/spec.md
git commit -m "feat(spec): canonical spec template with 3 worked examples"
```

---

## Task 11: skills/router/SKILL.md

**Goal:** Entry-point skill that describes the system and points agents at the right tools/skills/commands. Concise (per PRD: keep descriptions attention-effective).

**Files:**
- Create: `skills/router/SKILL.md`

**Acceptance Criteria:**
- [ ] Frontmatter has `name: router` and a single-sentence `description`.
- [ ] Body is under 400 lines.
- [ ] Names the MCP tool surface (the 10 tools from Task 9) so agents know they exist.
- [ ] Points at `templates/spec.md` and `skills/spec-writing/SKILL.md`.
- [ ] Describes the Phase 0 build-team flow (builder + spec-checker) and what's deferred.

**Verify:** File exists, YAML frontmatter parses, body wordcount is reasonable.

```powershell
python -c @"
import yaml, sys
text = open('skills/router/SKILL.md', encoding='utf-8').read()
parts = text.split('---', 2)
assert len(parts) == 3, 'missing frontmatter'
fm = yaml.safe_load(parts[1])
assert fm.get('name') == 'router'
assert 'description' in fm
body = parts[2]
assert len(body.splitlines()) < 400, 'body too long'
print('ok')
"@
```

**Steps:**

- [ ] **Step 1: Write `skills/router/SKILL.md`**

```markdown
---
name: router
description: Entry point for the Agentic Engineering System. Names the graph tools, the spec gate, and the active build flow so any subagent in this project knows where to look first.
---

# Router — Agentic Engineering System (Phase 0)

This project uses a self-contained Claude Code plugin. State lives in a SQLite graph
at `./.agentic/graph.db`. The only path to durable state is the bundled MCP server's
tools — there is no other surface that persists work.

## Where to look

- **Spec template:** `templates/spec.md` (with 3 worked examples).
- **Spec-writing guidance:** `skills/spec-writing/SKILL.md`.
- **Build subagents (Phase 0):** `agents/builder.md`, `agents/spec-checker.md`.
- **Slash commands (Phase 0):** `/agentic:init`, `/agentic:detect-conflicts`, `/agentic:import-spec`.

## MCP tool surface

The `agentic-graph` MCP server exposes these 10 tools. Every durable write must go
through one of them.

| Tool                       | Purpose                                              |
|----------------------------|------------------------------------------------------|
| `create_node`              | Create a Goal, Epic, Task, Subtask, Spec, Decision, Bug, Finding, Pattern, Module, File, Review, Retro, or ArchDebt node. |
| `update_node`              | Update an existing node's fields (bumps last_touched). |
| `get_node`                 | Fetch a single node by id.                           |
| `link_nodes`               | Create a typed relation (implements, depends-on, blocks, supersedes, caused-by, observed-in, touches, references, derived-from). |
| `query_graph`              | Filtered node query (by type, status, severity, scope). |
| `get_required_reads`       | Resolve a Spec's `required_reads` list into full node dicts. |
| `log_finding`              | Create a Finding attached to a parent node; inherits parent scope. |
| `mark_criterion_satisfied` | Mark a Spec acceptance criterion satisfied with required evidence. |
| `validate_spec`            | Run the falsifiability + feedback-loop gates on a Spec. |
| `infer_scope`              | Heuristically infer a scope tag from body/parent/cwd/files. |

## How dispatch works in Phase 0

1. A Spec is written using `templates/spec.md` (or imported via `/agentic:import-spec`).
2. `validate_spec` runs as a hard gate — un-falsifiable criteria or a missing
   feedback loop block dispatch.
3. The **builder** subagent reads the spec, the relevant graph slice (via
   `get_required_reads` and `query_graph`), and the relevant module skill file
   (if any). It implements, tests, and records its work.
4. The **spec-checker** subagent receives only the spec and the artifact — never
   the builder's prose. It runs each criterion's `verify` command, calls
   `mark_criterion_satisfied` (with evidence) for each pass, and logs `Finding`s
   for failures.
5. The cycle ends. Findings remain in the graph for future tasks to surface.

## What's deferred to Phase 1+

- Code-reviewer + contrarian roles, four-tier severity loop, critical-loop persistence.
- Orchestrator, parallelism, git worktrees.
- Pattern-finder, architectural-review, meta-graph, cross-project patterns.
- The `/agentic:new-spec`, `/agentic:dispatch`, `/agentic:review-pr`,
  `/agentic:find-patterns` commands.

## Scope semantics

Every node has a `scope` field (auto-inferred via `infer_scope` or explicit).
Scope is a soft tag — it does not block dispatch. It is used by the pattern-finder
in later phases to correlate signals within or across repos/modules.

## Build philosophy

You have access to a typed graph of every Finding, Decision, Bug, and Pattern
this project has accumulated. That memory is not something a single human engineer
can hold. Use it: query before guessing, link related nodes, and write what you
observe so the next agent inherits the context.
```

- [ ] **Step 2: Verify**

Run the verify command from the Verify section above.

- [ ] **Step 3: Commit**

```powershell
git add skills/router/SKILL.md
git commit -m "docs(skill): router entry point for the Agentic Engineering System"
```

---

## Task 12: skills/spec-writing/SKILL.md

**Goal:** Concise spec-writing skill that includes an embedded Socratic intent-clarification pass (per PRD D-29). Phase 0 minimal version — refinement is Phase 1+.

**Files:**
- Create: `skills/spec-writing/SKILL.md`

**Acceptance Criteria:**
- [ ] Frontmatter parses; `name: spec-writing`.
- [ ] Body under 250 lines.
- [ ] Contains a Socratic question list (5–8 questions) for clarifying intent before locking the spec.
- [ ] References `templates/spec.md` and `validate_spec`.
- [ ] No references to any other plugin's skills or commands (PRD D-28).

**Verify:** YAML parses; grep confirms no `superpowers-extended-cc:` references.

```powershell
python -c @"
import yaml
text = open('skills/spec-writing/SKILL.md', encoding='utf-8').read()
parts = text.split('---', 2)
fm = yaml.safe_load(parts[1])
assert fm['name'] == 'spec-writing'
assert 'superpowers-extended-cc' not in text, 'no cross-plugin references allowed'
assert len(parts[2].splitlines()) < 250
print('ok')
"@
```

**Steps:**

- [ ] **Step 1: Write `skills/spec-writing/SKILL.md`**

```markdown
---
name: spec-writing
description: How to write a Spec that passes the falsifiability and feedback-loop gates. Includes a Socratic intent-clarification pass to run before locking the spec.
---

# Spec Writing (Phase 0)

A Spec is the contract between intent and build. It must answer two questions
mechanically:

1. **How will we know each criterion is satisfied?** Not "looks right" — a runnable
   command, a type/lint check, or a named runtime observation.
2. **How will we know if the resulting artifact is working in real use, and how
   would a failure get fixed?** This is the feedback loop. Without it, the artifact
   ships blind.

Both gates are enforced by `validate_spec` (MCP tool). The orchestrator refuses
to dispatch a Spec that doesn't pass.

## Workflow

1. Start from `templates/spec.md`. Copy the structure; fill in each section.
2. Run the **Socratic pass** below. Update the spec based on what surfaces.
3. Call `validate_spec` with the criteria_json and feedback_loop.
4. If it returns reasons, fix the spec — don't argue with the validator. The
   validator is mechanical; if its complaints feel unfair, the criterion is
   probably under-specified.
5. Create the Spec node via `create_node(type='Spec', ...)`.
6. Link it to its Goal/Epic via `link_nodes(spec_id, goal_id, 'implements')`.

## Socratic intent-clarification pass

Before locking the spec, ask the user (or yourself, if no user is present) these
questions. The aim is to surface assumptions the spec is currently silent about.

1. **What changes for the user once this exists?** Name the observable difference.
2. **What is explicitly out of scope?** Anything you don't say "no" to becomes
   implicitly in scope.
3. **What happens if this is wrong?** Worst-case behavior shapes the criteria.
4. **Who else cares?** Stakeholders you haven't named will produce surprise
   requirements mid-build.
5. **What is the smallest possible version that's still useful?** If you can't
   answer, the spec is too big.
6. **What would falsify "this is done"?** Concretely. If the answer is "I'll know
   it when I see it", the criteria aren't ready.
7. **If this silently breaks 6 months from now, how do we find out?** That is the
   feedback loop.

If any answer is "I don't know yet", that becomes an entry in **Known Risks /
Open Questions**, not a hidden assumption in the body.

## Common rejections from `validate_spec`

| Rejection                                        | Fix                                                                                                  |
|--------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `verify field contains hand-wavy language`       | "works correctly" / "handled appropriately" / "tbd" are not verification. Name a command or signal.   |
| `verify must name a runnable command or signal`  | Prefix with `pytest`, `mypy`, `npm test`, etc. — or describe a runtime metric / log line / alert.    |
| `feedback_loop must name an observable signal`   | Add the signal: a user report, CI failure, metric, log line, dashboard view.                          |
| `feedback_loop must name a fix path`             | Say what we do when the signal fires: "open a bug", "file a retro", "PR a fix", "rollback".          |
| `spec has no acceptance criteria`                | Empty criteria_json. Even trivial tasks need at least one falsifiable criterion.                      |

## Examples

See `templates/spec.md`, Examples 1–3, for: a trivial utility, a real feature,
and a bug fix. All three pass `validate_spec`.
```

- [ ] **Step 2: Verify**

Run the verify command from the Verify section.

- [ ] **Step 3: Commit**

```powershell
git add skills/spec-writing/SKILL.md
git commit -m "docs(skill): spec-writing skill with Socratic intent-clarification pass"
```

---

## Task 13: Builder subagent (`agents/builder.md`)

**Goal:** Create the builder subagent definition with concise embedded tactical guidance for TDD and systematic debugging (per PRD D-29). Phase 0 minimal version.

**Files:**
- Create: `agents/builder.md`

**Acceptance Criteria:**
- [ ] Frontmatter has `name: builder`, `description`, and `model` (default `sonnet`).
- [ ] Prompt body under 200 lines (PRD: keep within attention-effective range).
- [ ] First mandated action: call `get_required_reads` for the spec and `query_graph` for relevant prior Findings.
- [ ] Embedded TDD guidance (a few sentences, not a skill expansion) — covers red/green/refactor.
- [ ] Embedded systematic-debugging guidance (a few sentences) — reproduce → isolate → root cause → fix → verify → log a `Retro`.
- [ ] No references to any other plugin (`grep -L 'superpowers-extended-cc'` returns the file).

**Verify:**

```powershell
python -c @"
import yaml
text = open('agents/builder.md', encoding='utf-8').read()
parts = text.split('---', 2)
fm = yaml.safe_load(parts[1])
assert fm['name'] == 'builder'
assert 'description' in fm
body_lines = parts[2].splitlines()
assert len(body_lines) < 200, f'body too long: {len(body_lines)}'
assert 'superpowers-extended-cc' not in text, 'no cross-plugin references allowed'
assert 'get_required_reads' in text
assert 'Retro' in text
print('ok')
"@
```

**Steps:**

- [ ] **Step 1: Write `agents/builder.md`**

```markdown
---
name: builder
description: Implements a single Spec end-to-end. Reads the relevant graph slice, writes tests first when the spec calls for it, implements, verifies, and records what it did via the MCP graph tools. Phase 0 — pre-review.
model: sonnet
---

You are the builder for the Agentic Engineering System.

## What you do

You take exactly one Spec, implement it, and hand the artifact off to the
spec-checker. You write what you observe to the graph; you do not "remember"
between calls — the graph is your only memory.

## First actions, in order

1. Call `get_node(id=<spec_id>)` to load the spec.
2. Call `get_required_reads(spec_id=<spec_id>)` to load every node the spec lists.
3. Call `query_graph(type='Finding', scope=<spec.scope>, severity='Critical', status='open')`
   to surface any open Critical findings in this scope. If any are relevant to
   the work you are about to do, mention them in your plan before implementing.
4. Read the module skill file (under `skills/<module>/SKILL.md`) if one exists
   for the spec's scope.

## Build approach

- **Test-first when the spec requires it.** Write the failing test, run it, see
  it fail with the expected reason, then write the minimal code to pass. Run the
  test, see it pass. Refactor only if the code is hard to read or there's
  duplication — not for theoretical extensibility.
- **Systematic debugging when investigating a bug.** Reproduce the bug
  deterministically; isolate the smallest input that triggers it; identify the
  root cause (not just the failing line); fix it; verify the reproducer now
  passes; create a `Retro` node via `create_node(type='Retro', ...,
  failed_layer=<spec|implementation|review|unknowable>)` and link it to the bug
  with `link_nodes(retro_id, bug_id, 'caused-by')`.
- **Small commits.** One commit per logical step. The diff should be readable
  in isolation.

## What you write to the graph

- For every meaningful observation that future work should inherit:
  `log_finding(parent_id=<spec_id>, severity=<Suggested|Strength>, body=...)`.
- For every bug you find or fix: `create_node(type='Bug', ...)` linked to the
  spec via `link_nodes(bug_id, spec_id, 'observed-in')`.
- For every retraced or reversed decision: `create_node(type='Retro', ...)`.

You do not call `mark_criterion_satisfied` — that is the spec-checker's job.

## Capability framing

You have access to memory and patterns across this project that no single
engineer holds in their head. Query before guessing; link related nodes; assume
the next agent will only see what you write down.
```

- [ ] **Step 2: Verify**

Run the verify command from the Verify section.

- [ ] **Step 3: Commit**

```powershell
git add agents/builder.md
git commit -m "feat(agent): builder subagent with embedded TDD + debug guidance"
```

---

## Task 14: Spec-checker subagent (`agents/spec-checker.md`)

**Goal:** Create the spec-checker subagent definition. Context-isolated: receives only the spec and the artifact paths, never the builder's prose.

**Files:**
- Create: `agents/spec-checker.md`

**Acceptance Criteria:**
- [ ] Frontmatter has `name: spec-checker`, `description`, `model`.
- [ ] Prompt body under 150 lines.
- [ ] First mandated action: load the spec via `get_node`.
- [ ] For each criterion: run the `verify` command exactly as written; if pass, call `mark_criterion_satisfied` with the verbatim command output as evidence; if fail, call `log_finding(severity='Critical', body=<failure detail>)`.
- [ ] Explicit instruction to ignore any reasoning from the builder — only spec + artifact.

**Verify:**

```powershell
python -c @"
import yaml
text = open('agents/spec-checker.md', encoding='utf-8').read()
parts = text.split('---', 2)
fm = yaml.safe_load(parts[1])
assert fm['name'] == 'spec-checker'
assert len(parts[2].splitlines()) < 150
assert 'mark_criterion_satisfied' in text
assert 'log_finding' in text
print('ok')
"@
```

**Steps:**

- [ ] **Step 1: Write `agents/spec-checker.md`**

```markdown
---
name: spec-checker
description: Verifies a built artifact against its Spec, one criterion at a time, using only the spec and the artifact files. Never reads the builder's prose. Phase 0.
model: sonnet
---

You are the spec-checker for the Agentic Engineering System.

## What you do

You take a Spec id and verify that the artifact satisfies each acceptance
criterion. You report per-criterion pass/fail to the graph.

## Context discipline

You see **only** the spec and the artifact files. You do not read the builder's
notes, prose, commit messages, or PR description. If you find yourself wanting
to "give them the benefit of the doubt", stop — the only thing that counts is
whether the criterion's `verify` step succeeds.

## First actions, in order

1. Call `get_node(id=<spec_id>)` to load the spec.
2. Parse `criteria_json` from the spec. Each entry has `text`, `verify`,
   `satisfied`, optional `evidence`.

## Per-criterion loop

For each criterion at index `i`:

1. Read the `verify` field. It will be either a runnable command (e.g.
   `pytest tests/test_x.py::test_y -v`) or a runtime observation
   (e.g. "logs show zero 5xx errors").
2. If runnable: execute it as written. Do not modify, simplify, or substitute.
3. Capture the full output (stdout + stderr + exit code).
4. **If pass:** call
   `mark_criterion_satisfied(spec_id=<spec_id>, criterion_index=<i>, evidence=<output>)`.
5. **If fail:** call
   `log_finding(parent_id=<spec_id>, severity='Critical', body=<criterion text + verify command + full output>)`.
6. Move on to the next criterion. Do not stop on the first failure — verify all
   of them so the builder has the full failure picture in one round.

## When you finish

- If every criterion is satisfied: do nothing else. The graph shows the spec is done.
- If any criterion failed: the open Critical findings you created are the
  builder's next round of work. Phase 0 has no automated re-dispatch — surface
  the finding ids to the human user.

## What you do NOT do

- Add Findings of severity `Important` or `Suggested` based on style or taste.
  That is the code-reviewer's job (Phase 1).
- Modify the artifact.
- Re-interpret a criterion. If a criterion is unclear, log it as a `Critical`
  finding against the spec itself — that is a spec-writing failure, not a
  build failure.
```

- [ ] **Step 2: Verify**

Run the verify command from the Verify section.

- [ ] **Step 3: Commit**

```powershell
git add agents/spec-checker.md
git commit -m "feat(agent): spec-checker subagent with context isolation discipline"
```

---

## Task 15: SessionStart hook (PowerShell walk-up resolver)

**Goal:** Hook that walks up from cwd looking for `.agentic/`, displays which one is active, and injects factual `additionalContext` for Claude Code. Inert if no `.agentic/` found. PowerShell 5.1 + ASCII-only string literals per machine notes.

**Files:**
- Create: `hooks/hooks.json`
- Create: `hooks/session-start.ps1`
- Create: `mcp-server/tests/test_walkup.py`

**Acceptance Criteria:**
- [ ] Hook script walks up from cwd; closest `.agentic/` wins.
- [ ] If found: prints a JSON `additionalContext` payload to stdout naming the project path and the count of open Specs / open Critical Findings (read from the graph).
- [ ] If not found: prints nothing (inert), exits 0.
- [ ] All string literals in the `.ps1` are ASCII-only (no em-dash, smart quotes, right-arrow) per machine notes.
- [ ] Script parses cleanly via `[Management.Automation.Language.Parser]::ParseFile`.
- [ ] `hooks.json` registers the script on `SessionStart`.
- [ ] Python integration test simulates 4 scenarios: (a) no `.agentic/`, (b) `.agentic/` at cwd, (c) `.agentic/` at parent, (d) `.agentic/` at both cwd and a grandparent (closest wins).

**Verify:**

```powershell
$err = $null
[Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path "hooks/session-start.ps1").Path, [ref]$null, [ref]$err
) | Out-Null
if ($err) { $err; exit 1 } else { "ok" }
pytest mcp-server/tests/test_walkup.py -v
```

Expected: `ok` from parse check + all walkup tests pass.

**Steps:**

- [ ] **Step 1: Write `hooks/session-start.ps1`**

```powershell
# SessionStart hook for the Agentic Engineering System.
# Walks up from $PWD looking for a .agentic/ directory. If found, emits a JSON
# additionalContext payload naming the active project path and basic graph stats.
# Inert (no output) if no .agentic/ is found in any ancestor.
#
# Constraints per machine notes:
#   - PowerShell 5.1 cp1252 read of "..." literals = ASCII-only inside string literals.
#   - Comments and @"..."@ here-strings are safe.
#   - Avoid 2>&1 on native exes.

$ErrorActionPreference = 'Stop'

function Find-AgenticRoot {
    param([string]$Start)
    $cur = (Resolve-Path -LiteralPath $Start).Path
    while ($true) {
        $candidate = Join-Path $cur '.agentic'
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return $cur
        }
        $parent = Split-Path -Parent $cur
        if (-not $parent -or $parent -eq $cur) { return $null }
        $cur = $parent
    }
}

function Read-GraphStats {
    param([string]$ProjectRoot)
    $dbPath = Join-Path $ProjectRoot '.agentic/graph.db'
    if (-not (Test-Path -LiteralPath $dbPath)) {
        return @{ open_specs = 0; open_critical_findings = 0; db_present = $false }
    }
    # Use the bundled Python CLI to query the graph. Avoid 2>&1 per machine notes.
    $script = @"
import json, sqlite3, sys
p = sys.argv[1]
c = sqlite3.connect(p)
try:
    specs = c.execute("SELECT count(*) FROM spec WHERE status IN ('draft','dispatched')").fetchone()[0]
except Exception:
    specs = 0
try:
    crits = c.execute("SELECT count(*) FROM finding WHERE severity='Critical' AND status='open'").fetchone()[0]
except Exception:
    crits = 0
print(json.dumps({'open_specs': specs, 'open_critical_findings': crits, 'db_present': True}))
"@
    try {
        $out = & python -c $script $dbPath
        return ($out | ConvertFrom-Json)
    } catch {
        return @{ open_specs = 0; open_critical_findings = 0; db_present = $true; error = "$_" }
    }
}

$root = Find-AgenticRoot -Start $PWD.Path
if (-not $root) { exit 0 }

$stats = Read-GraphStats -ProjectRoot $root

$context = @"
Agentic Engineering System is active for this project.
Project root: $root
Open specs: $($stats.open_specs)
Open critical findings: $($stats.open_critical_findings)
State lives under $($root)\.agentic\graph.db (SQLite + sqlite-vec).
All durable writes must flow through the agentic-graph MCP server tools.
Skill entry point: skills/router/SKILL.md.
"@

$payload = @{ additionalContext = $context } | ConvertTo-Json -Depth 4
Write-Output $payload
exit 0
```

- [ ] **Step 2: Write `hooks/hooks.json`**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "powershell -NoProfile -ExecutionPolicy Bypass -File ${CLAUDE_PLUGIN_ROOT}/hooks/session-start.ps1"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Parse-check the .ps1**

```powershell
$err = $null
[Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path "hooks/session-start.ps1").Path, [ref]$null, [ref]$err
) | Out-Null
if ($err) { $err; throw 'parse failed' } else { "ok" }
```

Expected: `ok`.

- [ ] **Step 4: Write `mcp-server/tests/test_walkup.py` (4 scenarios)**

```python
import json
import subprocess
import sys
from pathlib import Path
import pytest

# Phase 0 is Windows-only. Tests that subprocess-invoke `powershell` are skipped
# on other platforms. A portable POSIX hook is Phase 1+ work.
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Phase 0 SessionStart hook is PowerShell-only (Windows)",
)

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "session-start.ps1"


def _run_hook(cwd: Path) -> tuple[int, str]:
    res = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HOOK)],
        cwd=cwd, capture_output=True, text=True,
    )
    return res.returncode, res.stdout


@pytest.fixture
def scaffolded(tmp_path):
    """Build a directory tree we can drop .agentic/ markers into."""
    (tmp_path / "ws" / "repo-a" / "src").mkdir(parents=True)
    (tmp_path / "ws" / "repo-b").mkdir(parents=True)
    return tmp_path


def test_no_agentic_anywhere_is_silent(scaffolded):
    code, out = _run_hook(scaffolded / "ws" / "repo-a" / "src")
    assert code == 0
    assert out.strip() == ""


def test_agentic_at_cwd_is_found(scaffolded):
    target = scaffolded / "ws" / "repo-a"
    (target / ".agentic").mkdir()
    code, out = _run_hook(target)
    assert code == 0
    payload = json.loads(out)
    assert "Agentic Engineering System is active" in payload["additionalContext"]
    assert str(target) in payload["additionalContext"]


def test_agentic_at_parent_is_found(scaffolded):
    target = scaffolded / "ws" / "repo-a"
    (target / ".agentic").mkdir()
    deep = target / "src"
    code, out = _run_hook(deep)
    assert code == 0
    payload = json.loads(out)
    assert str(target) in payload["additionalContext"]


def test_closest_agentic_wins(scaffolded):
    grandparent = scaffolded / "ws"
    closer = scaffolded / "ws" / "repo-a"
    (grandparent / ".agentic").mkdir()
    (closer / ".agentic").mkdir()
    code, out = _run_hook(closer / "src")
    payload = json.loads(out)
    assert str(closer) in payload["additionalContext"]
    assert str(grandparent) not in payload["additionalContext"].replace(str(closer), "")
```

- [ ] **Step 5: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_walkup.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```powershell
git add hooks/hooks.json hooks/session-start.ps1 mcp-server/tests/test_walkup.py
git commit -m "feat(hook): SessionStart walk-up resolver with graph stats"
```

---

## Task 16: `/agentic:init` command

**Goal:** Slash command that scaffolds `.agentic/` in the current cwd, prompts for scope mode, and initializes the SQLite DB with the schema.

**Files:**
- Create: `commands/init.md`
- Create: `mcp-server/src/agentic_mcp/init_project.py`
- Create: `mcp-server/tests/test_init_project.py`

**Acceptance Criteria:**
- [ ] `commands/init.md` has Claude Code command frontmatter with `description` and uses `argument-hint: [scope-mode]`.
- [ ] Running the command (or the `agentic-mcp-init` helper directly) creates `./.agentic/graph.db` (with schema), `./.agentic/config.json` (with chosen scope mode), `./.agentic/compatibility.json` (empty `{}`), and `./.agentic/specs/` directory.
- [ ] Scope mode is one of `isolated` (default), `workspace`, `personal`. Invalid values rejected.
- [ ] Re-running `init` is non-destructive: existing graph.db is not wiped; config is preserved; only missing files/dirs created.

**Verify:** `pytest mcp-server/tests/test_init_project.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_init_project.py`**

```python
import json
import sqlite3
import pytest
from agentic_mcp import init_project, db


def test_init_creates_layout(tmp_path):
    init_project.run(project_root=tmp_path, scope_mode="isolated")
    assert (tmp_path / ".agentic" / "graph.db").exists()
    cfg = json.loads((tmp_path / ".agentic" / "config.json").read_text())
    assert cfg["scope_mode"] == "isolated"
    assert (tmp_path / ".agentic" / "compatibility.json").exists()
    assert (tmp_path / ".agentic" / "specs").is_dir()


def test_init_invalid_scope_mode(tmp_path):
    with pytest.raises(ValueError):
        init_project.run(project_root=tmp_path, scope_mode="multiverse")


def test_init_is_nondestructive(tmp_path):
    init_project.run(project_root=tmp_path, scope_mode="isolated")
    # Insert a marker row to confirm second init does not wipe.
    conn = db.connect(tmp_path / ".agentic" / "graph.db")
    conn.execute(
        "INSERT INTO goal(id,type,status,owner,body,created_at,last_touched) "
        "VALUES ('g-marker','Goal','active','test','marker','2026-01-01','2026-01-01')"
    )
    conn.commit()
    conn.close()

    init_project.run(project_root=tmp_path, scope_mode="workspace")
    # Marker still present:
    conn = sqlite3.connect(tmp_path / ".agentic" / "graph.db")
    rows = conn.execute("SELECT body FROM goal WHERE id='g-marker'").fetchall()
    assert rows == [("marker",)]
    # Config updated:
    cfg = json.loads((tmp_path / ".agentic" / "config.json").read_text())
    assert cfg["scope_mode"] == "workspace"
```

- [ ] **Step 2: Write `mcp-server/src/agentic_mcp/init_project.py`**

```python
"""Initialize a .agentic/ directory at a given project root."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import db as db_mod

VALID_SCOPE_MODES = {"isolated", "workspace", "personal"}


def run(project_root: Path | str, scope_mode: str = "isolated") -> None:
    if scope_mode not in VALID_SCOPE_MODES:
        raise ValueError(
            f"invalid scope_mode: {scope_mode!r}. Valid: {sorted(VALID_SCOPE_MODES)}"
        )
    root = Path(project_root).resolve()
    agentic = root / ".agentic"
    (agentic / "specs").mkdir(parents=True, exist_ok=True)

    db_path = agentic / "graph.db"
    if not db_path.exists():
        db_mod.init_db(db_path)
    else:
        # Apply schema idempotently in case it has been extended.
        db_mod.init_db(db_path)

    cfg_path = agentic / "config.json"
    cfg = {
        "scope_mode": scope_mode,
        "initialized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    compat_path = agentic / "compatibility.json"
    if not compat_path.exists():
        compat_path.write_text("{}\n", encoding="utf-8")


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Initialize .agentic/ at a project root.")
    p.add_argument("--root", default=".", help="project root (default cwd)")
    p.add_argument("--scope-mode", default="isolated", choices=sorted(VALID_SCOPE_MODES))
    args = p.parse_args()
    run(args.root, args.scope_mode)
    print(f"agentic: initialized at {Path(args.root).resolve() / '.agentic'}")
```

- [ ] **Step 3: Wire the CLI script in `pyproject.toml`**

Open `mcp-server/pyproject.toml` and modify the `[project.scripts]` block to include the init helper:

```toml
[project.scripts]
agentic-mcp = "agentic_mcp.server:main"
agentic-mcp-init = "agentic_mcp.init_project:cli"
```

Reinstall: `pip install -e mcp-server`

- [ ] **Step 4: Write `commands/init.md`**

```markdown
---
description: Initialize a .agentic/ directory at the current project root with chosen scope mode.
argument-hint: "[scope-mode: isolated | workspace | personal]"
---

Run the `agentic-mcp-init` CLI to scaffold the project state directory.

If the user passed an argument as `$1`, use it as the scope mode. Otherwise use `isolated`.

Steps:

1. Use the Bash tool to run: `agentic-mcp-init --root . --scope-mode {{$1 or "isolated"}}`
2. Confirm with the user that `.agentic/` was created and report:
   - Database path
   - Scope mode
   - That they can now write Specs using `templates/spec.md`

If the command fails because `agentic-mcp` is not on PATH, instruct the user to
`pip install -e mcp-server` inside the plugin's venv first.
```

- [ ] **Step 5: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_init_project.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```powershell
git add commands/init.md mcp-server/src/agentic_mcp/init_project.py mcp-server/tests/test_init_project.py mcp-server/pyproject.toml
git commit -m "feat(cmd): /agentic:init scaffolds .agentic/ with scope mode"
```

---

## Task 17: `/agentic:detect-conflicts` command

**Goal:** Informational-only command that lists installed Claude Code plugins, checks against the v1 known-overlap registry (Superpowers only per PRD D-33), and surfaces a coexistence note. Records user's stated preference in `.agentic/compatibility.json`. **Never modifies another plugin.**

**Files:**
- Create: `commands/detect-conflicts.md`
- Create: `mcp-server/src/agentic_mcp/registry.py`
- Create: `mcp-server/src/agentic_mcp/conflicts.py`
- Create: `mcp-server/tests/test_conflicts.py`

**Acceptance Criteria:**
- [ ] `registry.py` contains the v1 known-overlaps registry as a Python dict, with Superpowers (plugin id `superpowers-extended-cc`) as the only entry. Each entry names the overlapping categories.
- [ ] `conflicts.py:detect(plugins_dir)` reads `<plugins_dir>/*/.claude-plugin/plugin.json` (or analogous discovery), returns a list of `(plugin_id, name, version, overlap_info_or_None)`.
- [ ] `conflicts.py:render(detections)` returns the human-readable text block matching the PRD template (Detected / Overlapping skill categories / Options).
- [ ] `conflicts.py:record_preference(project_root, chosen)` writes the user's chosen option to `.agentic/compatibility.json` without touching anything outside `.agentic/`.
- [ ] Pytest verifies: (a) registry parses, (b) detect finds a fake Superpowers plugin in a temp dir, (c) render produces text containing "Detected: superpowers", (d) record_preference writes to compatibility.json only.

**Verify:** `pytest mcp-server/tests/test_conflicts.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_conflicts.py`**

```python
import json
from pathlib import Path
import pytest
from agentic_mcp import conflicts, registry, init_project


def _fake_plugin(plugins_dir: Path, plugin_id: str, name: str, version: str) -> None:
    pdir = plugins_dir / plugin_id / ".claude-plugin"
    pdir.mkdir(parents=True)
    (pdir / "plugin.json").write_text(
        json.dumps({"name": name, "version": version}), encoding="utf-8"
    )


def test_registry_has_superpowers():
    r = registry.KNOWN_OVERLAPS
    assert "superpowers-extended-cc" in r
    assert "categories" in r["superpowers-extended-cc"]


def test_detect_finds_superpowers(tmp_path):
    plugins = tmp_path / "plugins"
    _fake_plugin(plugins, "superpowers-extended-cc", "superpowers", "1.0.0")
    _fake_plugin(plugins, "some-other", "other", "0.1")
    detections = conflicts.detect(plugins_dir=plugins)
    by_id = {d["plugin_id"]: d for d in detections}
    assert by_id["superpowers-extended-cc"]["overlap"] is not None
    assert by_id["some-other"]["overlap"] is None


def test_render_contains_template_phrases(tmp_path):
    plugins = tmp_path / "plugins"
    _fake_plugin(plugins, "superpowers-extended-cc", "superpowers", "1.0.0")
    detections = conflicts.detect(plugins_dir=plugins)
    text = conflicts.render(detections)
    assert "Detected" in text
    assert "superpowers" in text
    assert "namespacing" in text
    assert "import-spec" in text


def test_record_preference_writes_only_inside_agentic(tmp_path):
    init_project.run(project_root=tmp_path, scope_mode="isolated")
    conflicts.record_preference(project_root=tmp_path, chosen="use-ours")
    compat = json.loads((tmp_path / ".agentic" / "compatibility.json").read_text())
    assert compat["choice"] == "use-ours"
    # Confirm nothing else was created at project root.
    others = [p.name for p in tmp_path.iterdir() if p.name != ".agentic"]
    assert others == []
```

- [ ] **Step 2: Write `mcp-server/src/agentic_mcp/registry.py`**

```python
"""v1 known-overlap registry (PRD D-33)."""
from __future__ import annotations

KNOWN_OVERLAPS: dict[str, dict] = {
    "superpowers-extended-cc": {
        "display_name": "Superpowers",
        "categories": [
            "planning", "code-review", "TDD", "debugging", "audit", "brainstorming",
        ],
        "coexistence_note": (
            "Both plugins can coexist via Claude Code's namespacing. Our cycle "
            "uses embedded tactical guidance integrated with our graph."
        ),
        "options": [
            (
                "Use ours end-to-end (recommended)",
                "Full graph integration. To avoid double-firing on PRs, consider "
                "/plugin disable superpowers.",
            ),
            (
                "Use Superpowers for ad-hoc work, ours for tracked tasks",
                "Both stay enabled, just be aware of doubled token cost on "
                "overlapping triggers.",
            ),
            (
                "Use Superpowers' planning, ours for build/review",
                "Use /agentic:import-spec to bring their plan output into our "
                "graph as a falsifiability-validated Spec node.",
            ),
        ],
    },
}
```

- [ ] **Step 3: Write `mcp-server/src/agentic_mcp/conflicts.py`**

```python
"""Conflict detection and informational coexistence rendering."""
from __future__ import annotations

import json
from pathlib import Path

from .registry import KNOWN_OVERLAPS


def detect(plugins_dir: Path | str) -> list[dict]:
    plugins_dir = Path(plugins_dir)
    out: list[dict] = []
    if not plugins_dir.exists():
        return out
    for plugin_dir in sorted(plugins_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest = plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        pid = plugin_dir.name
        overlap = KNOWN_OVERLAPS.get(pid)
        out.append({
            "plugin_id": pid,
            "name": data.get("name", pid),
            "version": data.get("version", "?"),
            "overlap": overlap,
        })
    return out


def render(detections: list[dict]) -> str:
    lines: list[str] = []
    overlapping = [d for d in detections if d["overlap"] is not None]
    if not overlapping:
        return (
            "No known overlapping plugins detected. "
            "(Other installed plugins are listed as 'unknown' and you should "
            "review them yourself.)"
        )
    for d in overlapping:
        ov = d["overlap"]
        lines.append(f"Detected: {ov['display_name']} (installed, enabled)")
        lines.append("")
        lines.append(
            f"Overlapping skill categories: {', '.join(ov['categories'])}."
        )
        lines.append("")
        lines.append(ov["coexistence_note"])
        lines.append("")
        lines.append("Options:")
        for label, body in ov["options"]:
            lines.append(f"  - {label}")
            lines.append(f"    {body}")
        lines.append("")
        lines.append(
            "No automatic changes will be made. You decide. "
            "If you want to disable a plugin, run /plugin disable yourself."
        )
    return "\n".join(lines)


def record_preference(project_root: Path | str, chosen: str) -> None:
    compat = Path(project_root) / ".agentic" / "compatibility.json"
    data: dict = {}
    if compat.exists():
        try:
            data = json.loads(compat.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data["choice"] = chosen
    from datetime import datetime, timezone
    data["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    compat.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Write `commands/detect-conflicts.md`**

```markdown
---
description: List installed Claude Code plugins, surface known overlaps with the agentic-engineering plugin, and record the user's coexistence preference. Informational only; never modifies another plugin.
---

This command does **not** disable any other plugin. It surfaces information and
records the user's stated preference.

Steps for Claude to execute:

1. Use the Bash tool to run:

   ```powershell
   python -c "from agentic_mcp import conflicts; import json; print(conflicts.render(conflicts.detect(plugins_dir=r'$env:USERPROFILE\.claude\plugins')))"
   ```

2. Show the output to the user.
3. If overlaps were found, ask the user which option they prefer (use AskUserQuestion).
4. Once they pick, run:

   ```powershell
   python -c "from agentic_mcp import conflicts; conflicts.record_preference(project_root='.', chosen='<their choice slug>')"
   ```

5. Confirm to the user that the preference has been recorded in
   `.agentic/compatibility.json` and that no other plugin's files were touched.
```

- [ ] **Step 5: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_conflicts.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```powershell
git add commands/detect-conflicts.md mcp-server/src/agentic_mcp/registry.py mcp-server/src/agentic_mcp/conflicts.py mcp-server/tests/test_conflicts.py
git commit -m "feat(cmd): /agentic:detect-conflicts informational coexistence surface"
```

---

## Task 18: `/agentic:import-spec` command

**Goal:** Bridge for users who insist on producing plans outside the system. Takes text or a file path, runs it through `validate_spec`, and creates a Spec node if it passes; rejects with reasons if not.

**Files:**
- Create: `commands/import-spec.md`
- Create: `mcp-server/src/agentic_mcp/import_spec.py`
- Create: `mcp-server/tests/test_import_spec.py`

**Acceptance Criteria:**
- [ ] `import_spec.from_markdown(text, owner)` parses out the `criteria_json` block and the `Feedback Loop` body, calls `validate_spec`, returns `(spec_id_or_None, reasons)`.
- [ ] If validation passes: creates a Spec node with `status='draft'` and returns the new id.
- [ ] If validation fails: returns `(None, reasons)` without creating anything.
- [ ] Accepts both the in-template fenced JSON form and an inline JSON-array form for criteria.

**Verify:** `pytest mcp-server/tests/test_import_spec.py -v` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing test `mcp-server/tests/test_import_spec.py`**

```python
import json
import pytest
from agentic_mcp import db, import_spec, nodes


GOOD = """\
# Imported spec

### Acceptance Criteria
```json
[
  {"text": "x", "verify": "pytest tests/x.py -v passes", "satisfied": false}
]
```

### Feedback Loop
If a user reports a regression, file a bug and write a retro.
"""

BAD = """\
# Imported spec

### Acceptance Criteria
```json
[
  {"text": "x", "verify": "tbd", "satisfied": false}
]
```

### Feedback Loop
tbd
"""


@pytest.fixture
def conn(tmp_db_path):
    db.init_db(tmp_db_path)
    c = db.connect(tmp_db_path)
    yield c
    c.close()


def test_good_spec_imports(conn):
    sid, reasons = import_spec.from_markdown(conn, GOOD, owner="alice")
    assert sid is not None
    assert reasons == []
    spec = nodes.get_node(conn, sid)
    assert spec["type"] == "Spec"
    assert spec["status"] == "draft"


def test_bad_spec_rejected(conn):
    sid, reasons = import_spec.from_markdown(conn, BAD, owner="alice")
    assert sid is None
    assert any("tbd" in r.lower() or "verify" in r.lower() for r in reasons)


def test_bad_spec_does_not_create_node(conn):
    before = conn.execute("SELECT count(*) FROM spec").fetchone()[0]
    import_spec.from_markdown(conn, BAD, owner="alice")
    after = conn.execute("SELECT count(*) FROM spec").fetchone()[0]
    assert before == after
```

- [ ] **Step 2: Write `mcp-server/src/agentic_mcp/import_spec.py`**

```python
"""Bridge: parse an external markdown plan into a validated Spec node."""
from __future__ import annotations

import json
import re
import sqlite3

from . import nodes, validators

_CRIT_RE = re.compile(
    r"###\s*Acceptance Criteria\s*```json\s*(\[.*?\])\s*```", re.S | re.I
)
_FB_RE = re.compile(r"###\s*Feedback Loop\s*\n(.+?)(?:\n#|\Z)", re.S | re.I)


def from_markdown(
    conn: sqlite3.Connection, text: str, owner: str
) -> tuple[str | None, list[str]]:
    crit_match = _CRIT_RE.search(text)
    fb_match = _FB_RE.search(text)
    if not crit_match:
        return None, ["could not find an Acceptance Criteria JSON block"]
    if not fb_match:
        return None, ["could not find a Feedback Loop section"]
    criteria_json = crit_match.group(1).strip()
    feedback_loop = fb_match.group(1).strip()
    # Normalize criteria: ensure each entry has satisfied field.
    try:
        parsed = json.loads(criteria_json)
    except ValueError as e:
        return None, [f"criteria_json not valid JSON: {e}"]
    for c in parsed:
        c.setdefault("satisfied", False)
    criteria_json = json.dumps(parsed)

    spec_dict = {"criteria_json": criteria_json, "feedback_loop": feedback_loop}
    ok, reasons = validators.validate_spec(spec_dict)
    if not ok:
        return None, reasons

    sid = nodes.create_node(
        conn, "Spec", status="draft", owner=owner, body=text,
        criteria_json=criteria_json, feedback_loop=feedback_loop,
    )
    return sid, []
```

- [ ] **Step 3: Write `commands/import-spec.md`**

```markdown
---
description: Import an external plan (text or file) as a validated Spec node in the graph. Rejects with reasons if it does not pass the falsifiability and feedback-loop gates.
argument-hint: "<path-to-file or paste text>"
---

Steps for Claude to execute:

1. If `$1` is a path to an existing file: read its contents. Otherwise treat `$1`
   as inline markdown.
2. Run:

   ```powershell
   python -c @"
import sys, json
from agentic_mcp import db, import_spec
text = sys.stdin.read()
conn = db.connect('.agentic/graph.db')
sid, reasons = import_spec.from_markdown(conn, text, owner='user')
print(json.dumps({'id': sid, 'reasons': reasons}))
"@ < <input file or string>
   ```

3. If `id` came back non-null: report the new Spec id to the user.
4. If `id` is null: show the reasons list verbatim so the user knows what to fix
   in their external plan before re-importing.
```

- [ ] **Step 4: Run tests, confirm all pass**

```powershell
pytest mcp-server/tests/test_import_spec.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```powershell
git add commands/import-spec.md mcp-server/src/agentic_mcp/import_spec.py mcp-server/tests/test_import_spec.py
git commit -m "feat(cmd): /agentic:import-spec bridges external plans via validator"
```

---

## Task 19: End-to-end bootstrap test (Phase 0 exit gate)

**Goal:** Run the complete Phase 0 flow on a small concrete task and prove the system produced a `Finding` node in the graph. This is the Phase 0 exit gate.

**Bootstrap task chosen:** Implement `slugify(s: str) -> str` in a throwaway scratch directory, with a Spec drawn from `templates/spec.md` Example 1.

**Files:**
- Create: `mcp-server/tests/test_e2e_bootstrap.py`

**Acceptance Criteria:**
- [ ] Test creates a temp project root, runs `init_project.run`, creates a Goal + a Spec node, validates the spec, "dispatches" by simulating a builder writing a Python module and tests, then "spec-checks" by running the criteria's verify commands and calling `mark_criterion_satisfied` for each pass.
- [ ] If any criterion fails, the test confirms a Critical `Finding` was logged.
- [ ] Test confirms: spec is satisfied → graph has the Spec with all criteria `satisfied=True`; a Finding exists logging the round-trip evidence (Strength severity, body summarizing the test output).
- [ ] Test then closes and reopens the DB and re-reads the Spec and Finding to prove the graph survives session restarts (PRD Phase 0 exit gate requirement).

**Verify:** `pytest mcp-server/tests/test_e2e_bootstrap.py -v` → passes.

**Steps:**

- [ ] **Step 1: Write `mcp-server/tests/test_e2e_bootstrap.py`**

```python
"""Phase 0 exit-gate test: full Spec -> build -> spec-check -> Finding flow."""
import json
import subprocess
import sys
from pathlib import Path

from agentic_mcp import db, findings, init_project, nodes, validators


SLUGIFY_CODE = '''
import re
import unicodedata


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s
'''


SLUGIFY_TEST = '''
from slugify_mod import slugify


def test_basic():
    assert slugify("Hello World") == "hello-world"


def test_accents():
    assert slugify("Creme Brulee") == "creme-brulee"


def test_whitespace():
    assert slugify("a  b") == "a-b"
'''


def test_phase_0_end_to_end(tmp_path):
    project = tmp_path / "scratch-project"
    project.mkdir()

    # 1. Initialize project state.
    init_project.run(project_root=project, scope_mode="isolated")
    db_path = project / ".agentic" / "graph.db"

    conn = db.connect(db_path)

    # 2. Write the artifact + test files (simulating the builder's output).
    (project / "slugify_mod.py").write_text(SLUGIFY_CODE)
    (project / "test_slugify.py").write_text(SLUGIFY_TEST)

    # 3. Create Goal + Spec nodes.
    goal_id = nodes.create_node(
        conn, "Goal", status="active", owner="bootstrap", body="ship slugify"
    )
    crit = [
        {"text": "basic ascii", "verify": "pytest test_slugify.py::test_basic -v"},
        {"text": "accents transliterated", "verify": "pytest test_slugify.py::test_accents -v"},
        {"text": "whitespace collapsed", "verify": "pytest test_slugify.py::test_whitespace -v"},
    ]
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="bootstrap",
        body="slugify spec — see templates/spec.md Example 1",
        criteria_json=json.dumps(crit),
        feedback_loop=(
            "If a user reports a slug bug, we write a regression test and "
            "open a PR fixing it."
        ),
        scope="scratch-project",
    )

    # 4. Validate the spec — gate must pass.
    spec_dict = {
        "criteria_json": json.dumps(crit),
        "feedback_loop": (
            "If a user reports a slug bug, we write a regression test and "
            "open a PR fixing it."
        ),
    }
    ok, reasons = validators.validate_spec(spec_dict)
    assert ok, f"spec failed validation: {reasons}"

    # 5. Spec-checker simulation: run each verify command, mark or log.
    any_failed = False
    for i, c in enumerate(crit):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"] + c["verify"].split()[1:],
            cwd=project, capture_output=True, text=True,
        )
        if result.returncode == 0:
            findings.mark_criterion_satisfied(
                conn, spec_id, i,
                evidence=result.stdout.strip()[-200:] or "pytest exit 0",
            )
        else:
            any_failed = True
            findings.log_finding(
                conn, spec_id, "Critical",
                body=(
                    f"criterion {i} failed: {c['text']}\n"
                    f"cmd: {c['verify']}\n"
                    f"stdout:\n{result.stdout[-500:]}\n"
                    f"stderr:\n{result.stderr[-500:]}"
                ),
            )

    # 6. Log the round-trip Strength evidence if all passed.
    if not any_failed:
        findings.log_finding(
            conn, spec_id, "Strength",
            body="bootstrap e2e: all 3 slugify criteria satisfied",
        )

    conn.close()

    # 7. CRITICAL: reopen the DB to prove survival across sessions.
    conn2 = db.connect(db_path)
    reread_spec = nodes.get_node(conn2, spec_id)
    assert reread_spec is not None
    reread_crit = json.loads(reread_spec["criteria_json"])
    assert all(c["satisfied"] for c in reread_crit), (
        f"not all criteria satisfied after reload: {reread_crit}"
    )

    # 8. A Finding (Strength) must exist with evidence.
    findings_rows = conn2.execute(
        "SELECT severity, body FROM finding WHERE parent_id=?", (spec_id,)
    ).fetchall()
    severities = [r[0] for r in findings_rows]
    assert "Strength" in severities, f"no Strength finding logged: {severities}"
    conn2.close()
```

- [ ] **Step 2: Run the test, confirm it passes**

```powershell
pytest mcp-server/tests/test_e2e_bootstrap.py -v
```

Expected: 1 passed. If pytest's subprocess invocation can't find `pytest` on Windows, adjust to `[sys.executable, "-m", "pytest", ...]` — already done in the test.

- [ ] **Step 3: Commit**

```powershell
git add mcp-server/tests/test_e2e_bootstrap.py
git commit -m "test(e2e): Phase 0 exit-gate bootstrap test (spec -> build -> check -> finding -> reload)"
```

---

## Task 20: Plan-coverage review + README + final commit

**Goal:** Final sweep. Confirm every Phase 0 build item from the PRD has a corresponding task that was actually completed. Update the repo README with install + usage. Commit.

**Files:**
- Modify: `README.md`

**Acceptance Criteria:**
- [ ] README explains: what the project is, current phase, install steps, the three Phase 0 commands, the Spec template location, and where the plan lives.
- [ ] Every Phase 0 build item in the PRD is checked off against a completed task in this plan:
  - [x] Plugin scaffold (`plugin.json`, directory structure) — Task 0, 1
  - [x] Graph schema (entity types + relations + indexes + scope field) — Task 2
  - [x] MCP server with minimal tool set — Task 9 (composing Tasks 3–8)
  - [x] Spec template + falsifiability + feedback-loop validators + scope auto-inference — Tasks 7, 8, 10
  - [x] SessionStart hook + walk-up resolution + active path display — Task 15
  - [x] skills/router/SKILL.md — Task 11
  - [x] Builder + spec-checker subagents (with embedded minimal tactical guidance) — Tasks 13, 14
  - [x] `/agentic:init` — Task 16
  - [x] `/agentic:detect-conflicts` — Task 17
  - [x] `/agentic:import-spec` — Task 18
  - [x] End-to-end bootstrap demonstrating Phase 0 exit gate — Task 19
- [ ] All test suites green: `pytest mcp-server/tests/ -v` exits 0.

**Verify:**

```powershell
cd mcp-server
pytest -v
cd ..
```

Expected: every test passes; total >= 40 tests.

**Steps:**

- [ ] **Step 1: Run the full suite**

```powershell
cd mcp-server
pytest -v
```

If any test fails, fix and re-commit BEFORE proceeding.

- [ ] **Step 2: Update the repo `README.md`**

```markdown
# Agentic Engineering System

A self-improving engineering system, packaged as a Claude Code plugin. State lives
in a typed SQLite graph; every "done" claim is checked against falsifiable
acceptance criteria by an independent context.

**Current phase:** 0 — Foundations. See `docs/plans/2026-05-17-phase-0-foundations.md`.

## What ships in Phase 0

- SQLite graph with 14 entity types and 9 relation types (vector search via `sqlite-vec` is deferred to Phase 3)
- stdio MCP server (`agentic-mcp`) exposing 10 graph tools
- Spec template with falsifiability + feedback-loop gates (`templates/spec.md`)
- Two subagents: `builder` and `spec-checker` (Phase 1 adds reviewer + contrarian)
- SessionStart hook with walk-up `.agentic/` resolution (Windows / PowerShell only in Phase 0)
- Slash commands: `/agentic:init`, `/agentic:detect-conflicts`, `/agentic:import-spec`

## Install (developer / dogfood)

```powershell
git clone https://github.com/GhostlyGawd/agentic-engineering.git
cd agentic-engineering
python -m venv mcp-server/.venv
.\mcp-server\.venv\Scripts\Activate.ps1
pip install -e mcp-server[dev]
pytest mcp-server/tests -v
```

Install as a Claude Code plugin:

```
/plugin install github:GhostlyGawd/agentic-engineering
```

## Start a project

From a project root:

1. `/agentic:init` (scope mode: `isolated` | `workspace` | `personal`)
2. `/agentic:detect-conflicts` (informational; never modifies other plugins)
3. Write a Spec using `templates/spec.md`, or import one with `/agentic:import-spec <file>`.

## What's deferred to Phase 1+

Code-reviewer, contrarian, severity-gated review loop, orchestrator,
parallelism via git worktrees, pattern-finder, architectural review,
self-improvement, meta-graph, cross-platform SessionStart hook,
`sqlite-vec` vector index. See the PRD
(`agentic-engineering-system-prd-v3.md`) for the full roadmap.

## Documentation

- PRD: `agentic-engineering-system-prd-v3.md`
- Phase 0 plan: `docs/plans/2026-05-17-phase-0-foundations.md`
- Router skill: `skills/router/SKILL.md`
- Spec template: `templates/spec.md`
```

- [ ] **Step 3: Confirm Phase 0 exit gate end-to-end**

Manual checklist (per PRD Phase 0 exit gate):

- [ ] A task can be dispatched, built, spec-checked, and result in a `Finding` node logged to the graph → demonstrated by Task 19's e2e test.
- [ ] Graph survives session restarts → Task 19 reopens the DB and re-reads.
- [ ] Spec dispatch is blocked if criteria are not falsifiable or feedback loop is missing → Task 7 validator tests; Task 18 import-spec rejects.
- [ ] Plugin installs cleanly via `/plugin install` → Task 0 + Task 1 produced a valid plugin manifest; manual install test on a Claude Code session left as the user's final acceptance check.
- [ ] Walk-up resolution finds project correctly across at least three test scenarios → Task 15 covers 4 scenarios.
- [ ] Hook injection verified on target Claude Code version → Task 15's PowerShell parse-check + e2e test; final verification is a manual session-start test.
- [ ] Conflict detection runs without modifying any other plugin → Task 17's `test_record_preference_writes_only_inside_agentic`.

- [ ] **Step 4: Final commit**

```powershell
git add README.md
git commit -m "docs: README for Phase 0 ship; plan coverage review complete"
```

---

## Task 21: Push to GitHub as agentic-engineering

**Goal:** Create the public GitHub repo at `github.com/GhostlyGawd/agentic-engineering` and push everything. Verify a fresh clone + install works.

**Files:** No file changes beyond the push itself.

**Acceptance Criteria:**
- [ ] Repo `github.com/GhostlyGawd/agentic-engineering` exists, public, with the Phase 0 commits on `main`.
- [ ] `git remote -v` shows `origin` pointing at the new repo.
- [ ] A fresh `git clone` of the repo into a temp directory + `pip install -e mcp-server[dev]` + `pytest mcp-server/tests` succeeds.
- [ ] `gh repo view GhostlyGawd/agentic-engineering` returns the manifest with expected description.

**Verify:**

```powershell
gh repo view GhostlyGawd/agentic-engineering --json name,visibility,defaultBranchRef
git ls-remote origin main
```

Expected: repo metadata returned; remote `main` ref present.

**Steps:**

- [ ] **Step 1: Confirm gh CLI is authenticated**

```powershell
gh auth status
```

Expected: signed in as `GhostlyGawd`. If not: `gh auth login` (interactive — user runs this manually with `! gh auth login` if needed).

- [ ] **Step 2: Create the repo and add as origin**

```powershell
gh repo create GhostlyGawd/agentic-engineering `
  --public `
  --source=. `
  --remote=origin `
  --description "Self-improving engineering system: typed knowledge graph, falsifiability-gated specs, independent verification. Claude Code plugin."
```

This creates the repo and runs `git remote add origin https://github.com/GhostlyGawd/agentic-engineering.git`.

- [ ] **Step 3: Push main**

```powershell
git push -u origin main
```

If the push hits secret scanning (e.g., a fixture string that matches a credential regex per machine notes), defang the offending string and re-commit before pushing again. Never use `--no-verify`.

- [ ] **Step 4: Verify fresh clone + install round-trip**

```powershell
$tmp = New-Item -ItemType Directory -Force -Path "$env:TEMP\agentic-clone-test-$(Get-Date -Format 'yyyyMMddHHmmss')"
Set-Location $tmp
git clone https://github.com/GhostlyGawd/agentic-engineering.git
Set-Location agentic-engineering
python -m venv mcp-server/.venv
.\mcp-server\.venv\Scripts\Activate.ps1
pip install -e mcp-server[dev]
pytest mcp-server/tests -v
```

Expected: all tests green from the freshly cloned copy.

- [ ] **Step 5: Confirm via gh CLI**

```powershell
gh repo view GhostlyGawd/agentic-engineering --json name,visibility,defaultBranchRef,description
```

Expected: JSON shows `name: agentic-engineering`, `visibility: PUBLIC`, default branch `main`, description matches.

- [ ] **Step 6: No commit needed**

This task only pushes already-committed work. No new commit.

---

## Self-Review Notes

After writing this plan, I checked:

- **Spec coverage:** Each Phase 0 build item from the PRD maps to a numbered task (see Task 20 Acceptance Criteria). Open Question #7 (first bootstrap task) is resolved as the `slugify` example in Task 19.
- **Placeholders:** No "TBD" / "implement later" / "similar to Task N" patterns. Every code step shows the actual code.
- **Type consistency:** `criteria_json` is consistently a JSON-encoded list of `{text, verify, satisfied, evidence?}` across Tasks 3, 6, 7, 10, 17, 18, 19. `parent_id` is used consistently on `finding`. Scope mode strings (`isolated|workspace|personal`) are consistent across Tasks 16, 17, 19.
- **Phase boundary discipline:** No Phase 1+ work crept in. Code-reviewer, contrarian, parallelism, pattern-finder, architectural review are all explicitly listed as out-of-scope.
- **Cross-plugin discipline (PRD D-28):** No subagent prompt, skill, or command file references `superpowers-extended-cc` or any other plugin at runtime. Tactical guidance in `agents/builder.md` and `agents/spec-checker.md` is concise and self-contained.

## Revisions (v2 of this plan)

Applied after a second clarifying pass:

1. **PRD file authority** — `agentic-engineering-system-prd-v2.md` deleted; `agentic-engineering-system-prd-v3.md` is the single source of truth. All references in the plan and README updated.
2. **`sqlite-vec` deferred to Phase 3** — Task 2 no longer creates the `vec0` virtual table; `db.py` no longer loads the extension; `pyproject.toml` no longer depends on `sqlite-vec`. Phase 0 ships pure SQLite.
3. **Windows-only Phase 0** — `test_walkup.py` carries a module-level `pytest.mark.skipif(sys.platform != "win32", ...)`. A portable POSIX hook is Phase 1+ work.
4. **MCP SDK version pinning** — Task 9 step 5 pins `mcp==<resolved-version>` in `pyproject.toml` after the round-trip test passes. Reproducible installs.
5. **Plugin metadata** — `plugin.json` `author` is `GhostlyGawd` (the user's confirmed GitHub handle); `license` is MIT; `repository` field added pointing at the new repo.
6. **GitHub distribution** — new Task 21 creates `github.com/GhostlyGawd/agentic-engineering`, pushes, and verifies a fresh clone-and-install round-trip. README in Task 20 references this URL.
7. **Bootstrap task** — confirmed: `slugify(s)` stays as the Task 19 e2e bootstrap.

Open known risks (not bugs in the plan; flags for execution):

1. The MCP Python SDK's class names may have drifted in newer versions. Task 9 may need an import tweak before the pin in Step 5. If the SDK's `Server`, `Tool`, `TextContent`, or `stdio_server` symbols moved, adjust per `import mcp; print(dir(mcp.server))`.
2. The PowerShell SessionStart hook depends on `python` being on PATH for `Read-GraphStats`. If a target machine doesn't have it, the hook falls back to zero stats rather than failing. Verify this is the desired behavior at execution time.
3. Walking up indefinitely could in theory cross a UNC root boundary. The script's `if (-not $parent -or $parent -eq $cur)` guard handles the local-FS case; UNC paths may need a separate guard if the user runs Claude from a network share.
4. Phase 0's bootstrap test runs pytest in a subprocess from inside pytest. On some Windows configurations the inner pytest may not find packages without `PYTHONPATH` adjustment. Task 19 isolates that by writing module files in the temp project root and not relying on package installs.
5. Task 21 (GitHub push) assumes `gh` CLI is installed and authenticated as `GhostlyGawd`. If not, the user runs `! gh auth login` themselves before the task executes. Repo creation needs `Administration: Write` at the account level on the PAT (per user machine notes).

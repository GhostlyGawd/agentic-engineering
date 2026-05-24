# Headless Build + Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the orchestrator's headless `tick()` actually build (a graph-assembled builder prompt) and actually review (headless `/agentic:review-pr`, verdict derived from the graph), replacing the contentless builder prompt and the rubber-stamp CLEAN review stub.

**Architecture:** Two new pure helpers compute everything graph-dependent in `tick()`'s single-threaded body (`_build_builder_prompt`, `_verdict_from_graph`); the thread-run `_real_launch` only consumes a pre-assembled prompt, and the single-threaded `_real_review` runs the review-pr loop then queries the graph for the verdict. The fast suite keeps stubbing every seam; new behavior is gated behind an `llm`-marked e2e and the two helpers' fast unit tests.

**Tech Stack:** Python 3.12, SQLite (`agentic_mcp` package), the headless `claude` CLI wrapper (`headless.py`), pytest (`-m "not llm"` fast suite vs `-m llm` live gate), git worktrees.

**Spec:** `docs/superpowers/specs/2026-05-23-headless-build-review-loop-design.md` (approved; REVISED 2026-05-24).

---

## Revision 2026-05-24 (post-live-e2e) - READ FIRST

The first live `llm` e2e run exposed two wrong assumptions invisible to the fast
suite. Status of the original Tasks 1-6 and the new work:

- **Tasks 1, 2, 3, 5: DONE and correct** (`_verdict_from_graph`, `_build_builder_prompt`,
  `_real_launch` rewrite, `tick()` wiring). Unchanged by this revision.
- **Task A (NEW, DONE): headless prompt via stdin.** `headless.run_claude_headless`
  now feeds the prompt over STDIN, not as a `-p` argv. A multi-line prompt passed
  as an argv to the Windows `claude.CMD` shim is truncated by `cmd.exe` at the first
  newline (dropping `--output-format json` too) -> non-JSON stdout -> build fails.
  Fixed + unit-tested (`test_run_claude_headless_passes_prompt_via_stdin`) +
  live-validated (build half now builds->commits->merges). Commit on this branch.
- **Task 4 (_real_review): SUPERSEDED.** The original "run `claude -p
  '/agentic:review-pr <spec_id>'`" cannot work - headless `-p` has NO custom slash
  commands (confirmed live: "Unknown command", and in the CC docs). The `_real_review`
  body and its 4 fast unit tests still stand for the verdict/error/never-raise
  behavior, but the COMMAND INVOCATION is replaced by Task B below.
- **Task B (NEW, TODO): inline-body + staged-agents review.** See revised Task 4
  section below.
- **Task 6 (e2e): UPDATED** for the new review path (stage agents; criterion-satisfied
  is the load-bearing assertion). The build-half assertions already pass live.

## Context an implementer must know first

- **Run pytest FROM `mcp-server/`** with the venv python: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`. The fast suite is currently `160 passed, 7 deselected`.
- **Module style:** `conn` is the first arg; call `conn.commit()` after writes (reads need none). `_now()` = `datetime.now(timezone.utc).isoformat(timespec="seconds")`.
- **Relations:** the only relevant types are `implements` (Task -> Spec) and `depends-on` (Task -> prereq). Resolve a task's spec with `relations.neighbors(conn, task_id, "implements", "out")` -> a list of spec ids.
- **Findings & verdict scope:** both `spec-checker` and `code-reviewer` log findings with `log_finding(parent_id=<spec_id>, severity='Critical', ...)`. `log_finding` sets `status='open'` and inherits `scope` from the parent. The e2e specs carry **no `scope`** (it is `None`), and `None` would match every other scope-less spec's findings — so the verdict query MUST key off **`parent_id == spec_id`**, NOT `scope`. The contract is "any open Critical for THIS spec -> NEEDS_FIXING". `query_graph` has no `parent_id` filter, so use a direct SELECT on the `finding` table.
- **Thread-safety (the constraint that shapes this whole design):** `headless.Pool` runs `launch_fn` in worker THREADS, and a `sqlite3.Connection` is not thread-safe. So anything that touches `conn` (prompt assembly, verdict query, MCP-config staging) happens in `tick()`'s single-threaded body and is passed into the job dict. `_real_launch` (thread) never touches `conn`. `_real_review` runs in `tick()`'s single-threaded review phase, so it MAY use `conn`.
- **`tick()` never-raise contract:** the review phase (step 6) has NO outer try/except. So `_real_review` MUST catch ALL of its own exceptions (including spec resolution) and return NEEDS_FIXING — never let one propagate, and never merge unreviewed code.
- **Existing helpers you will reuse (do not reimplement):**
  - `headless.run_claude_headless(prompt, cwd, timeout=900, mcp_config=None) -> dict` — runs `claude -p ... --output-format json --permission-mode bypassPermissions`; kills the process tree on timeout, raises `RuntimeError` on non-zero exit.
  - `headless.stage_mcp_config(project, db_path) -> Path` — writes a RESOLVED `.mcp.json` (using `sys.executable`) into `project`, registering the `agentic-graph` server. This works (the old "MCP never connected" memory was a different, bare-command config).
  - `headless.Pool(max_workers).run(jobs, launch_fn)` — thread pool; `launch_fn` MUST return a structured result, never raise.
  - `relations.neighbors`, `nodes.get_node`, `findings.log_finding`, `db.resolve_db_path`.
- **No non-ASCII** in any string literal you add (machine cp1252 gotcha). The prompt text in this plan is deliberately plain ASCII.

## File structure

| File | Responsibility | Change |
|------|----------------|--------|
| `mcp-server/src/agentic_mcp/orchestrate.py` | The tick + its seams | Add `_build_builder_prompt`, `_verdict_from_graph`; rewrite `_real_launch` and `_real_review`; wire `tick()` (new `db_path` param, stage MCP config, assemble prompts into jobs, enrich review input); pass `db_path` from `main()`. |
| `mcp-server/tests/test_orchestrate.py` | Fast unit + composition tests | Add fast unit tests for the two helpers and the two seam rewrites (claude monkeypatched). Existing tests stay green unchanged. |
| `mcp-server/tests/test_headless_loop_e2e.py` | Live end-to-end | New `llm`-marked, `skipif`-no-`claude` e2e: real builder builds, real review-pr gates to CLEAN, task merges + criterion satisfied. |

---

### Task 1: `_verdict_from_graph` pure helper

**Goal:** A pure function that returns the review verdict for a spec by counting its open Critical findings — no `claude`, fast-unit-testable.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/orchestrate.py` (add the helper near the other seam helpers, after `_real_review`)
- Test: `mcp-server/tests/test_orchestrate.py`

**Acceptance Criteria:**
- [ ] `_verdict_from_graph(conn, spec_id)` returns `{"verdict": "NEEDS_FIXING", ...}` when at least one open Critical finding has `parent_id == spec_id`.
- [ ] Returns `{"verdict": "CLEAN", ...}` when there are none.
- [ ] The returned dict carries `reviewer="code-reviewer"`, `hit=True`, `calibrate=False`.
- [ ] A Critical finding that is `resolved` (not `open`) does NOT count as a blocker.
- [ ] A Critical finding parented to a DIFFERENT spec does NOT count.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k verdict_from_graph -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** in `mcp-server/tests/test_orchestrate.py` (append after the existing tests; `findings` is not yet imported — add it to the existing `from agentic_mcp import ...` line, i.e. `from agentic_mcp import calibration, claims, db, findings, nodes, orchestrate, relations`):

```python
# --- _verdict_from_graph -------------------------------------------------
def test_verdict_from_graph_clean_when_no_open_critical(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        rv = orchestrate._verdict_from_graph(conn, spec)
        assert rv["verdict"] == "CLEAN"
        assert rv["reviewer"] == "code-reviewer"
        assert rv["hit"] is True
        assert rv["calibrate"] is False
    finally:
        conn.close()


def test_verdict_from_graph_needs_fixing_when_open_critical(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        findings.log_finding(conn, parent_id=spec, severity="Critical",
                             body="criterion 0 failed")
        rv = orchestrate._verdict_from_graph(conn, spec)
        assert rv["verdict"] == "NEEDS_FIXING"
    finally:
        conn.close()


def test_verdict_from_graph_ignores_resolved_critical(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        fid = findings.log_finding(conn, parent_id=spec, severity="Critical",
                                   body="was failing")
        nodes.update_node(conn, fid, status="resolved")
        rv = orchestrate._verdict_from_graph(conn, spec)
        assert rv["verdict"] == "CLEAN"
    finally:
        conn.close()


def test_verdict_from_graph_ignores_other_specs_critical(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec_a = _dispatched_spec(conn)
        spec_b = _dispatched_spec(conn)
        findings.log_finding(conn, parent_id=spec_b, severity="Critical",
                             body="b is broken")
        rv = orchestrate._verdict_from_graph(conn, spec_a)
        assert rv["verdict"] == "CLEAN"
    finally:
        conn.close()
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k verdict_from_graph -v`
Expected: FAIL with `AttributeError: module 'agentic_mcp.orchestrate' has no attribute '_verdict_from_graph'`

- [ ] **Step 3: Implement the helper** in `mcp-server/src/agentic_mcp/orchestrate.py`, immediately after the `_real_review` function (which Task 4 rewrites; for now add it after the current `_real_review`):

```python
def _verdict_from_graph(conn, spec_id: str) -> dict:
    """Derive a review verdict from the graph: any open Critical for this spec
    means NEEDS_FIXING, else CLEAN.

    Keys off parent_id (NOT scope): both spec-checker and code-reviewer log
    findings with parent_id=<spec_id>, and spec.scope is frequently None (which
    would collide across every scope-less spec). query_graph has no parent_id
    filter, so this is a direct SELECT. calibrate=False: at review time there is
    no ground truth for whether the verdict is correct, so it must not bias
    per-role calibration.
    """
    open_criticals = conn.execute(
        "SELECT COUNT(*) FROM finding "
        "WHERE parent_id=? AND severity='Critical' AND status='open'",
        (spec_id,),
    ).fetchone()[0]
    verdict = "NEEDS_FIXING" if open_criticals else "CLEAN"
    return {"verdict": verdict, "reviewer": "code-reviewer", "hit": True,
            "calibrate": False}
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k verdict_from_graph -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/orchestrate.py mcp-server/tests/test_orchestrate.py
git commit -m "feat(orchestrate): add _verdict_from_graph (open Critical -> NEEDS_FIXING)"
```

---

### Task 2: `_build_builder_prompt` pure helper

**Goal:** A pure function that reads a Task body + its parent Spec criteria from the graph and returns a self-contained builder-role prompt — no `claude`, fast-unit-testable.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/orchestrate.py` (add the helper after `_verdict_from_graph`)
- Test: `mcp-server/tests/test_orchestrate.py`

**Acceptance Criteria:**
- [ ] `_build_builder_prompt(conn, task_id)` returns a string containing the task's `body` text.
- [ ] The string contains every criterion's `text` from the parent spec's `criteria_json`.
- [ ] The string names the task id and the spec id.
- [ ] When the task has no parent spec, the function returns a prompt (does not raise) with the task body and a spec id of `(none)`.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k build_builder_prompt -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** in `mcp-server/tests/test_orchestrate.py`:

```python
# --- _build_builder_prompt -----------------------------------------------
def _spec_with_criteria(conn, criteria):
    return nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="spec body",
        criteria_json=json.dumps(criteria),
        feedback_loop="open a retro on failure",
    )


def test_build_builder_prompt_contains_task_body_and_criteria(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _spec_with_criteria(conn, [
            {"text": "alpha criterion holds", "verify": "pytest a"},
            {"text": "beta criterion holds", "verify": "pytest b"},
        ])
        tid = nodes.create_node(conn, "Task", status="pending", owner="t",
                                body="DO THE ALPHA THING", tags=json.dumps(["src/a/*"]))
        relations.link_nodes(conn, tid, spec, "implements")

        prompt = orchestrate._build_builder_prompt(conn, tid)

        assert "DO THE ALPHA THING" in prompt
        assert "alpha criterion holds" in prompt
        assert "beta criterion holds" in prompt
        assert tid in prompt
        assert spec in prompt
    finally:
        conn.close()


def test_build_builder_prompt_handles_missing_spec(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        tid = nodes.create_node(conn, "Task", status="pending", owner="t",
                                body="ORPHAN TASK", tags=json.dumps(["src/a/*"]))
        # No implements edge.
        prompt = orchestrate._build_builder_prompt(conn, tid)
        assert "ORPHAN TASK" in prompt
        assert "(none)" in prompt
    finally:
        conn.close()
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k build_builder_prompt -v`
Expected: FAIL with `AttributeError: module 'agentic_mcp.orchestrate' has no attribute '_build_builder_prompt'`

- [ ] **Step 3: Implement the helper** in `mcp-server/src/agentic_mcp/orchestrate.py`, after `_verdict_from_graph`:

```python
def _build_builder_prompt(conn, task_id: str) -> str:
    """Assemble a builder-role prompt from the Task body + parent Spec criteria.

    Pure (single-threaded; reads conn). tick() calls this BEFORE dispatch and
    passes the result into the job dict, so the thread-run _real_launch never
    touches conn. Embedded guidance mirrors agents/builder.md, kept concise.
    """
    task = nodes.get_node(conn, task_id)
    spec_ids = relations.neighbors(conn, task_id, "implements", "out")
    spec = nodes.get_node(conn, spec_ids[0]) if spec_ids else None

    criteria = []
    if spec and spec.get("criteria_json"):
        try:
            criteria = json.loads(spec["criteria_json"])
        except (TypeError, ValueError):
            criteria = []
    criteria_lines = "\n".join(
        f"  {i}. {c.get('text', '')} (verify: {c.get('verify', '')})"
        for i, c in enumerate(criteria)
    ) or "  (none)"

    spec_id = spec["id"] if spec else "(none)"
    return (
        "You are a builder agent implementing one task inside a git worktree.\n"
        f"Task id: {task_id}\n"
        f"Spec id: {spec_id}\n\n"
        "## Task\n"
        f"{task['body']}\n\n"
        "## Acceptance criteria (from the parent spec)\n"
        f"{criteria_lines}\n\n"
        "## Instructions\n"
        "- Implement the task in the CURRENT worktree directory.\n"
        "- Self-verify your work against each acceptance criterion above.\n"
        "- Commit your work with a descriptive message. Do NOT push.\n"
        "- Stop after committing.\n"
    )
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k build_builder_prompt -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/orchestrate.py mcp-server/tests/test_orchestrate.py
git commit -m "feat(orchestrate): add _build_builder_prompt (task body + spec criteria)"
```

---

### Task 3: Rewrite `_real_launch` to run the assembled prompt

**Goal:** `_real_launch` runs the graph-assembled prompt (from `job["prompt"]`) with the staged MCP config, and returns the worktree path so the review phase can find it. Verified fast by monkeypatching `claude` and `git`.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/orchestrate.py:74-87` (the `_real_launch` body; also remove the now-dead `_BUILDER_PROMPT` constant at lines 63-66)
- Test: `mcp-server/tests/test_orchestrate.py`

**Acceptance Criteria:**
- [ ] `_real_launch` calls `headless.run_claude_headless` with `job["prompt"]`, `cwd=job["worktree"]`, and `mcp_config=job.get("mcp_config")`.
- [ ] On success returns `{"task_id", "ok": True, "sha", "worktree"}` (the worktree is added so `_real_review` can locate it).
- [ ] On any exception returns `{"task_id", "ok": False, "error"}` (never raises into the Pool).
- [ ] The dead `_BUILDER_PROMPT` constant is removed.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k real_launch -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** in `mcp-server/tests/test_orchestrate.py` (add `import types` to the top-of-file imports if not present):

```python
# --- _real_launch (claude + git monkeypatched) ---------------------------
def test_real_launch_runs_prompt_and_returns_worktree(monkeypatch):
    calls = {}

    def fake_run(prompt, cwd, timeout=900, mcp_config=None):
        calls["prompt"] = prompt
        calls["cwd"] = cwd
        calls["mcp_config"] = mcp_config
        return {"result": "built"}

    monkeypatch.setattr(orchestrate.headless, "run_claude_headless", fake_run)
    monkeypatch.setattr(orchestrate, "_git",
                        lambda args: types.SimpleNamespace(stdout="abc123\n"))

    job = {"task_id": "t1", "worktree": "/wt/t1", "branch": "orch/t1",
           "prompt": "BUILD THIS", "mcp_config": "/repo/.mcp.json"}
    out = orchestrate._real_launch(job)

    assert out == {"task_id": "t1", "ok": True, "sha": "abc123",
                   "worktree": "/wt/t1"}
    assert calls["prompt"] == "BUILD THIS"
    assert calls["cwd"] == "/wt/t1"
    assert calls["mcp_config"] == "/repo/.mcp.json"


def test_real_launch_folds_exception_into_error(monkeypatch):
    def boom(prompt, cwd, timeout=900, mcp_config=None):
        raise RuntimeError("claude exploded")

    monkeypatch.setattr(orchestrate.headless, "run_claude_headless", boom)
    job = {"task_id": "t1", "worktree": "/wt/t1", "branch": "orch/t1",
           "prompt": "BUILD THIS", "mcp_config": None}
    out = orchestrate._real_launch(job)
    assert out["task_id"] == "t1"
    assert out["ok"] is False
    assert "claude exploded" in out["error"]
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k real_launch -v`
Expected: FAIL — current `_real_launch` calls `run_claude_headless(_BUILDER_PROMPT, cwd=...)` with no `mcp_config` and no `worktree` in the result, so `calls["prompt"]` and the result-dict assertions mismatch.

- [ ] **Step 3: Rewrite `_real_launch`** in `mcp-server/src/agentic_mcp/orchestrate.py`. Delete the `_BUILDER_PROMPT` constant (lines 63-66) and replace the `_real_launch` body:

```python
def _real_launch(job: dict) -> dict:
    """Run one builder agent headless against its graph-assembled prompt.

    The prompt and (optional) mcp_config are assembled in tick()'s single-
    threaded body and passed in via the job dict, because this function runs in
    a Pool worker THREAD and must never touch the sqlite connection.

    MUST catch its own exceptions: headless.Pool re-raises whatever launch_fn
    raises, which would abort the whole batch. So every failure is folded into
    {"ok": False, "error": ...} and the orchestrator routes it to `failed`.
    """
    tid = job["task_id"]
    try:
        headless.run_claude_headless(
            job["prompt"], cwd=job["worktree"], mcp_config=job.get("mcp_config"),
        )
        sha = _git(["-C", job["worktree"], "rev-parse", "HEAD"]).stdout.strip()
        # Carry the worktree forward: tick()'s review phase needs it to run
        # review-pr in the right directory (the launch result is what review_fn
        # receives as job_result).
        return {"task_id": tid, "ok": True, "sha": sha, "worktree": job["worktree"]}
    except Exception as e:  # noqa: BLE001 - launch_fn must never raise to the Pool
        return {"task_id": tid, "ok": False, "error": str(e)}
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k real_launch -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/orchestrate.py mcp-server/tests/test_orchestrate.py
git commit -m "feat(orchestrate): _real_launch runs assembled prompt, returns worktree"
```

---

### Task 4: Rewrite `_real_review` to run review-pr headless + derive verdict

> SUPERSEDED 2026-05-24 by Task B below. The verdict-derivation, error->NEEDS_FIXING,
> and never-raise behavior described here are correct and were implemented + tested.
> But the COMMAND INVOCATION (`claude -p "/agentic:review-pr <spec_id>"`) is
> infeasible (headless has no custom slash commands). Task B replaces the invocation
> with the inline-body + staged-agents approach. Read Task B for the current design.

**Goal:** `_real_review` resolves the task's spec, runs `/agentic:review-pr <spec_id>` headless in the worktree, then derives the verdict from the graph via `_verdict_from_graph`. ANY failure (no spec, claude crash/timeout, query error) returns NEEDS_FIXING — never merges unreviewed code, never raises.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/orchestrate.py:125-136` (the `_real_review` body)
- Test: `mcp-server/tests/test_orchestrate.py`

**Acceptance Criteria:**
- [ ] On a successful review-pr run with no open Critical -> verdict CLEAN.
- [ ] On a successful review-pr run with an open Critical for the spec -> verdict NEEDS_FIXING.
- [ ] On a `run_claude_headless` exception -> verdict NEEDS_FIXING (caught; does not raise).
- [ ] `run_claude_headless` is invoked with `cwd=job_result["worktree"]`, `mcp_config=job_result.get("mcp_config")`, and a prompt of the form `/agentic:review-pr <spec_id>`.
- [ ] A task with no parent spec -> verdict NEEDS_FIXING (caught, never raises — preserves tick()'s never-raise contract).

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k real_review -v` -> all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** in `mcp-server/tests/test_orchestrate.py`:

```python
# --- _real_review (claude monkeypatched; verdict from graph) --------------
def test_real_review_clean_when_no_open_critical(tmp_db_path, monkeypatch):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        seen = {}

        def fake_run(prompt, cwd, timeout=900, mcp_config=None):
            seen["prompt"] = prompt
            seen["cwd"] = cwd
            seen["mcp_config"] = mcp_config
            return {"result": "reviewed"}

        monkeypatch.setattr(orchestrate.headless, "run_claude_headless", fake_run)
        rv = orchestrate._real_review(
            conn, t1, {"worktree": "/wt/t1", "mcp_config": "/repo/.mcp.json"})

        assert rv["verdict"] == "CLEAN"
        assert rv["calibrate"] is False
        assert seen["cwd"] == "/wt/t1"
        assert seen["mcp_config"] == "/repo/.mcp.json"
        assert spec in seen["prompt"]
        assert "review-pr" in seen["prompt"]
    finally:
        conn.close()


def test_real_review_needs_fixing_when_open_critical(tmp_db_path, monkeypatch):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        findings.log_finding(conn, parent_id=spec, severity="Critical",
                             body="criterion failed")
        monkeypatch.setattr(orchestrate.headless, "run_claude_headless",
                            lambda *a, **k: {"result": "reviewed"})
        rv = orchestrate._real_review(
            conn, t1, {"worktree": "/wt/t1", "mcp_config": None})
        assert rv["verdict"] == "NEEDS_FIXING"
    finally:
        conn.close()


def test_real_review_needs_fixing_on_claude_failure(tmp_db_path, monkeypatch):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])

        def boom(*a, **k):
            raise RuntimeError("review-pr timed out")

        monkeypatch.setattr(orchestrate.headless, "run_claude_headless", boom)
        rv = orchestrate._real_review(
            conn, t1, {"worktree": "/wt/t1", "mcp_config": None})
        assert rv["verdict"] == "NEEDS_FIXING"
    finally:
        conn.close()


def test_real_review_needs_fixing_when_task_has_no_spec(tmp_db_path, monkeypatch):
    conn = _mk_conn(tmp_db_path)
    try:
        t1 = nodes.create_node(conn, "Task", status="pending", owner="t",
                               body="orphan", tags=json.dumps(["src/a/*"]))
        # No implements edge -> neighbors()[0] would IndexError; must be caught.
        monkeypatch.setattr(orchestrate.headless, "run_claude_headless",
                            lambda *a, **k: {"result": "reviewed"})
        rv = orchestrate._real_review(
            conn, t1, {"worktree": "/wt/t1", "mcp_config": None})
        assert rv["verdict"] == "NEEDS_FIXING"
    finally:
        conn.close()
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k real_review -v`
Expected: FAIL — the current `_real_review` ignores `claude` entirely and returns CLEAN unconditionally, so the NEEDS_FIXING and prompt-assertion cases fail.

- [ ] **Step 3: Rewrite `_real_review`** in `mcp-server/src/agentic_mcp/orchestrate.py`:

```python
def _real_review(conn, task_id: str, job_result: dict) -> dict:
    """Run the real /agentic:review-pr loop headless, then derive the verdict.

    review-pr IS the full four-role loop engine (spec-checker gate ->
    code-reviewer + contrarian -> builder loop-fix -> re-loop until clean or
    diminishing returns). One headless call runs the entire review-and-repair
    cycle and lands on a terminal state; we then read the graph for the verdict.

    Runs in tick()'s single-threaded review phase, so it MAY use conn. The
    review phase has NO outer try/except, so this function MUST catch ALL of its
    own exceptions (spec resolution included) and return NEEDS_FIXING - never
    merge unreviewed code, never raise. The Phase 2.1 retry cap then terminates
    a persistently unreviewable task after 3 strikes.
    """
    try:
        spec_id = relations.neighbors(conn, task_id, "implements", "out")[0]
        headless.run_claude_headless(
            f"/agentic:review-pr {spec_id}",
            cwd=job_result["worktree"],
            mcp_config=job_result.get("mcp_config"),
        )
        return _verdict_from_graph(conn, spec_id)
    except Exception:  # noqa: BLE001 - never merge unreviewed code; never raise
        return {"verdict": "NEEDS_FIXING", "reviewer": "code-reviewer",
                "hit": True, "calibrate": False}
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k real_review -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add mcp-server/src/agentic_mcp/orchestrate.py mcp-server/tests/test_orchestrate.py
git commit -m "feat(orchestrate): _real_review runs review-pr headless, verdict from graph"
```

---

### Task 5: Wire `tick()` — db_path, MCP staging, prompt assembly, review enrichment

**Goal:** `tick()` stages a resolved MCP config once per tick (live path only), assembles each dispatched task's builder prompt into its job dict, and enriches each launch result with the worktree + mcp_config before review. The fast suite (no `db_path`) is unaffected; `main()` passes the resolved `db_path`.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/orchestrate.py` — `tick()` signature + body (lines ~189-353) and `main()` (lines ~357-380)
- Test: `mcp-server/tests/test_orchestrate.py`

**Acceptance Criteria:**
- [ ] `tick()` accepts a new keyword param `db_path=None`.
- [ ] When `db_path is None` (the fast-suite default): NO `.mcp.json` is staged, and every existing fast test still passes unchanged.
- [ ] When `db_path` is set AND there is at least one dispatched job: `headless.stage_mcp_config(repo, db_path)` is called exactly once and each job dict carries `mcp_config` set to the staged path.
- [ ] Each dispatched job dict carries `prompt` = `_build_builder_prompt(conn, tid)`.
- [ ] When `db_path` is set but there are NO jobs (empty/idle graph), `stage_mcp_config` is NOT called (no `.mcp.json` side effect — this is what keeps `test_cli_main_prints_json` clean).
- [ ] Before `review_fn` is called, the launch result `r` carries `worktree` (from the dispatch bookkeeping) and `mcp_config` (the staged path or None).
- [ ] `main()` resolves `db_path` once and passes it to `tick()`.
- [ ] Full fast suite green: `pytest -m "not llm"` -> previous count + the new unit tests, 0 failures.

**Verify:** `./.venv/Scripts/python.exe -m pytest -m "not llm" -q` -> all pass (no failures); plus `-k tick_stages_mcp` for the new wiring tests.

**Steps:**

- [ ] **Step 1: Write the failing wiring tests** in `mcp-server/tests/test_orchestrate.py`. These assert the job dict and staging behavior by capturing what `launch_fn` receives:

```python
# --- tick() wiring: prompt assembly + mcp staging ------------------------
def test_tick_assembles_prompt_into_job(tmp_db_path):
    conn = _mk_conn(tmp_db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        captured = {}

        def capture_launch(job):
            captured[job["task_id"]] = job
            return {"task_id": job["task_id"], "ok": True, "sha": "x",
                    "worktree": job["worktree"]}

        orchestrate.tick(
            conn, launch_fn=capture_launch, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        job = captured[t1]
        assert "prompt" in job
        assert "task" in job["prompt"]  # body of _task() is "task"
        # No db_path -> no staging -> mcp_config is None (or absent).
        assert job.get("mcp_config") is None
    finally:
        conn.close()


def test_tick_stages_mcp_config_when_db_path_set(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        captured = {}

        def capture_launch(job):
            captured[job["task_id"]] = job
            return {"task_id": job["task_id"], "ok": True, "sha": "x",
                    "worktree": job["worktree"]}

        orchestrate.tick(
            conn, repo=str(repo), db_path=db_path,
            launch_fn=capture_launch, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        # .mcp.json staged into the repo, and the job points at it.
        assert (repo / ".mcp.json").exists()
        assert captured[t1]["mcp_config"] == repo / ".mcp.json"
    finally:
        conn.close()


def test_tick_no_mcp_stage_when_no_jobs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        # Empty graph: no tasks -> no jobs -> must NOT write .mcp.json.
        orchestrate.tick(
            conn, repo=str(repo), db_path=db_path,
            launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=fake_review_clean,
        )
        assert not (repo / ".mcp.json").exists()
    finally:
        conn.close()


def test_tick_enriches_review_input_with_worktree_and_mcp(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        spec = _dispatched_spec(conn)
        t1 = _task(conn, spec, ["src/a/*"])
        seen = {}

        def review_capture(conn_, tid, job_result):
            seen[tid] = dict(job_result)
            return {"verdict": "CLEAN", "reviewer": "code-reviewer",
                    "hit": True, "calibrate": False}

        orchestrate.tick(
            conn, repo=str(repo), db_path=db_path,
            launch_fn=fake_launch_ok, worktree_factory=fake_worktree,
            merge_fn=fake_merge_ok, review_fn=review_capture,
        )
        assert seen[t1]["worktree"] == f"/wt/{t1}"
        assert seen[t1]["mcp_config"] == repo / ".mcp.json"
    finally:
        conn.close()
```

Note: `fake_launch_ok` currently returns no `worktree` key. Update it (top of file) to carry the worktree so the enrichment test and any real-path symmetry hold:

```python
def fake_launch_ok(job):
    return {"task_id": job["task_id"], "ok": True, "sha": "deadbeef",
            "worktree": job["worktree"]}
```

- [ ] **Step 2: Run the new tests, verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k "tick_assembles_prompt or tick_stages_mcp or tick_no_mcp_stage or tick_enriches_review" -v`
Expected: FAIL — `tick()` has no `db_path` param (TypeError) / does not assemble `prompt` / does not stage `.mcp.json`.

- [ ] **Step 3: Add `db_path` to the `tick()` signature.** In `mcp-server/src/agentic_mcp/orchestrate.py`, add the param to the keyword-only block:

```python
def tick(
    conn,
    *,
    repo: str = ".",
    pool_size: int = 3,
    weed_days: int = 14,
    launch_fn=_real_launch,
    worktree_factory=_real_worktree,
    merge_fn=_real_merge,
    review_fn=_real_review,
    integration_branch: str | None = None,
    current_branch_fn=_real_current_branch,
    db_path=None,
) -> dict:
```

- [ ] **Step 4: Assemble the prompt + track worktrees in step 4.** In the step-4 batch loop, inside the existing `try` (after `nodes.update_node(conn, tid, status="in_progress")`), assemble the prompt and record the worktree; add `prompt` to the job dict. Replace the block from `wt, branch = worktree_factory(...)` through `result["dispatched"].append(tid)`:

```python
        try:
            wt, branch = worktree_factory(repo, tid)
            claims.attach_worktree(conn, cid, wt, branch)
            nodes.update_node(conn, tid, status="in_progress")
            # Assemble the builder prompt HERE (single-threaded, owns conn) so
            # the thread-run launch_fn never touches the sqlite connection.
            prompt = _build_builder_prompt(conn, tid)
        except Exception as e:  # noqa: BLE001 - setup failure must never propagate
            _handle_failure(conn, tid, cid, f"worktree/setup failure: {e}", result)
            result["failed"].append(tid)
            continue
        claim_ids[tid] = cid
        branches[tid] = branch
        worktrees[tid] = wt
        jobs.append({"task_id": tid, "worktree": wt, "branch": branch,
                     "prompt": prompt})
        result["dispatched"].append(tid)
```

Also declare `worktrees` alongside the other per-tick dicts at the top of step 4 (next to `claim_ids` / `branches`):

```python
    claim_ids: dict[str, str] = {}
    branches: dict[str, str] = {}
    worktrees: dict[str, str] = {}
    jobs: list[dict] = []
```

- [ ] **Step 5: Stage the MCP config once, after the batch loop, before dispatch.** Insert a new block between the end of step 4 and step 5 (`results = headless.Pool(...)`):

```python
    # 4b. Stage a resolved .mcp.json ONCE per tick so each worker/reviewer can
    # reach the agentic-graph server. Live path only: gated on db_path (the fast
    # suite passes none -> no staging, no file side effect) AND on having real
    # work (no jobs -> nothing to configure, e.g. an idle CLI tick).
    mcp_config = None
    if jobs and db_path is not None:
        mcp_config = headless.stage_mcp_config(repo, db_path)
        for job in jobs:
            job["mcp_config"] = mcp_config
```

- [ ] **Step 6: Enrich the launch result before review** in step 6. Replace the loop head:

```python
    for r in results:
        if not r.get("ok"):
            continue
        tid = r["task_id"]
        # tick() owns the worktree + staged mcp_config; inject them so the real
        # reviewer can run review-pr in the right directory with graph access,
        # regardless of what launch_fn put in its result.
        r["worktree"] = worktrees.get(tid, r.get("worktree"))
        r["mcp_config"] = mcp_config
        rv = review_fn(conn, tid, r)
```

- [ ] **Step 7: Pass `db_path` from `main()`.** Update `main()`:

```python
    db_path = db.resolve_db_path()
    conn = db.connect(db_path)
    try:
        result = tick(
            conn, repo=args.repo, pool_size=args.pool, weed_days=args.weed_days,
            integration_branch=args.integration_branch, db_path=db_path,
        )
    finally:
        conn.close()
```

- [ ] **Step 8: Run the new wiring tests, then the FULL fast suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrate.py -k "tick_assembles_prompt or tick_stages_mcp or tick_no_mcp_stage or tick_enriches_review" -v`
Expected: 4 passed

Run: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: previous 160 + the new unit tests (Tasks 1-5), 0 failures, 7 deselected.

- [ ] **Step 9: Commit**

```bash
git add mcp-server/src/agentic_mcp/orchestrate.py mcp-server/tests/test_orchestrate.py
git commit -m "feat(orchestrate): wire tick() for real build+review (db_path, mcp staging, prompt, review enrichment)"
```

---

### Task 6: Live `llm`-marked end-to-end (real build -> real review-pr -> merge)

**Goal:** An on-demand `llm`-marked e2e proving the closed loop: a dispatched Spec + Task, the REAL `_real_launch` builds the artifact from the graph-assembled prompt, the REAL `_real_review` runs `/agentic:review-pr` which gates it CLEAN, and `tick()` merges the branch — with the criterion marked satisfied in the graph.

**Files:**
- Create: `mcp-server/tests/test_headless_loop_e2e.py`

**Acceptance Criteria:**
- [ ] Test is marked `pytest.mark.llm` and `skipif(not headless.claude_on_path())`, so it is excluded from the fast suite and skips when `claude` is absent.
- [ ] Uses the REAL seams (`_real_launch`, `_real_worktree`, `_real_merge`, `_real_review`) — only `tick(..., db_path=...)` is supplied; no launch/review stubs.
- [ ] After the tick: the task is in `result["merged"]`, its node status is `merged`, its claim is `released`, and the built file exists in the repo working tree after merge.
- [ ] The spec's criterion is marked `satisfied` in `criteria_json` (review-pr's spec-checker ran the verify command and passed it).
- [ ] No prose/stdout inspection — assertions read structured graph + filesystem state only.

**Verify:** `./.venv/Scripts/python.exe -m pytest tests/test_headless_loop_e2e.py -m llm -v` (requires the `claude` CLI on PATH; long-running — two real `claude -p` sessions).

**Steps:**

- [ ] **Step 1: Write the e2e** at `mcp-server/tests/test_headless_loop_e2e.py`. It reuses the `_setup_git_repo` pattern from `test_phase2_e2e.py`. The criterion's `verify` is a cross-platform Python one-liner that passes once the builder creates the file (spec-checker runs it verbatim):

```python
# mcp-server/tests/test_headless_loop_e2e.py
"""Live e2e for the headless build+review loop (Task 6 of the headless loop plan).

llm-marked: excluded from the fast suite by `addopts = -m "not llm"`. Run on
demand against a live `claude` CLI:
    ./.venv/Scripts/python.exe -m pytest tests/test_headless_loop_e2e.py -m llm -v

Proves the closed loop end to end with the REAL seams: a dispatched Spec + Task,
real builder build (graph-assembled prompt), real /agentic:review-pr gate to
CLEAN, then merge. Two real `claude -p` sessions -> slow and subscription-metered;
never runs in the fast suite.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agentic_mcp import db, headless, nodes, orchestrate, relations

pytestmark = pytest.mark.llm


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True, encoding="utf-8")


def _setup_git_repo(repo: Path) -> None:
    _git(["init", "-b", "main"], cwd=str(repo))
    _git(["config", "user.name", "Test Runner"], cwd=str(repo))
    _git(["config", "user.email", "test@example.com"], cwd=str(repo))
    (repo / "README.txt").write_text("headless loop e2e base", encoding="utf-8")
    _git(["add", "README.txt"], cwd=str(repo))
    _git(["commit", "-m", "init: base commit for e2e"], cwd=str(repo))


@pytest.mark.skipif(
    not headless.claude_on_path(),
    reason="live claude CLI not on PATH",
)
def test_build_review_merge_closed_loop(tmp_path):
    # --- 1. Real git repo --------------------------------------------------
    repo = tmp_path / "repo"
    repo.mkdir()
    _setup_git_repo(repo)

    # --- 2. Graph DB (the staged mcp_config points workers at THIS file) ----
    db_path = tmp_path / "graph.db"
    db.init_db(db_path)
    conn = db.connect(db_path)

    # --- 3. Dispatched Spec + one Task implementing it ----------------------
    # The verify command is a cross-platform Python one-liner: exit 0 iff the
    # file exists. review-pr's spec-checker runs it verbatim in the worktree.
    verify = "python -c \"import os,sys; sys.exit(0 if os.path.exists('hello.txt') else 1)\""
    spec = nodes.create_node(
        conn, "Spec", status="dispatched", owner="e2e",
        body="Ship hello.txt containing the word OK.",
        criteria_json=json.dumps([{"text": "hello.txt exists", "verify": verify}]),
        feedback_loop="open a retro on failure",
    )
    task = nodes.create_node(
        conn, "Task", status="pending", owner="e2e",
        body="Create a file named hello.txt in the worktree root containing the word OK.",
        tags=json.dumps(["hello.txt"]),
    )
    relations.link_nodes(conn, task, spec, "implements")

    # --- 4. Run the real tick (all real seams; only db_path injected) -------
    try:
        result = orchestrate.tick(
            conn, repo=str(repo), pool_size=1, db_path=db_path,
        )
    finally:
        try:
            subprocess.run(["git", "worktree", "prune"],
                           cwd=str(repo), capture_output=True)
        except Exception:
            pass
        conn.close()

    # --- 5. Structured assertions (no prose inspection) ---------------------
    assert task in result["dispatched"], (
        f"task should dispatch; dispatched={result['dispatched']}, "
        f"failed={result['failed']}, escalations={result['escalations']}")
    assert task in result["merged"], (
        f"task should merge CLEAN; merged={result['merged']}, "
        f"escalations={result['escalations']}, failed={result['failed']}")
    assert not result["failed"], f"no failure expected; failed={result['failed']}"
    assert (repo / "hello.txt").exists(), "hello.txt missing after merge"

    conn2 = db.connect(db_path)
    try:
        node = nodes.get_node(conn2, task)
        assert node["status"] == "merged", f"task status={node['status']}"
        claim_rows = conn2.execute(
            "SELECT status FROM claim WHERE task_id=?", (task,)).fetchall()
        assert "released" in [r[0] for r in claim_rows], "claim not released"
        # review-pr's spec-checker marked the criterion satisfied.
        spec_node = nodes.get_node(conn2, spec)
        criteria = json.loads(spec_node["criteria_json"])
        assert criteria[0].get("satisfied") is True, (
            f"criterion not marked satisfied: {criteria[0]}")
    finally:
        conn2.close()
```

- [ ] **Step 2: Confirm it is excluded from the fast suite**

Run: `./.venv/Scripts/python.exe -m pytest -m "not llm" -q`
Expected: the new e2e is among the deselected (count rises to 8 deselected); fast suite still 0 failures.

- [ ] **Step 3: Run the live e2e** (requires `claude` on PATH; long-running)

Run: `./.venv/Scripts/python.exe -m pytest tests/test_headless_loop_e2e.py -m llm -v`
Expected: 1 passed. If `claude` is not on PATH: 1 skipped.

If it fails, debug against ACTUAL state (read the worktree, read the `finding` rows for `parent_id=spec`), NOT the claude prose — per the repo's "verify diffs, don't trust reports" lesson. A review timeout surfaces as NEEDS_FIXING (the task lands in `escalations`/`failed`, not `merged`); if that happens because review-pr legitimately needs more than the 900s default, raise the headless timeout rather than weakening the assertion.

- [ ] **Step 4: Commit**

```bash
git add mcp-server/tests/test_headless_loop_e2e.py
git commit -m "test(e2e): live headless build+review+merge closed-loop (llm-marked)"
```

> REVISED 2026-05-24: Task 6's e2e must now ALSO exercise the staged-agents review
> path (Task B). The build-half assertions (dispatched/merged/file-exists) already
> pass live; the criterion-satisfied assertion is load-bearing (it proves the
> staged spec-checker actually ran). After Task B lands, re-run the live e2e to
> confirm the full loop green.

---

### Task A: headless prompt via stdin (NEW 2026-05-24 - DONE)

**Goal:** `headless.run_claude_headless` delivers the prompt over STDIN, not as a `-p` argv, so multi-line prompts survive the Windows `claude.CMD` shim.

**Status:** DONE on this branch (commit `fix(headless): feed prompt via stdin ...`). Recorded here so the plan reflects reality.

**What changed:**
- `cmd` no longer contains the prompt; it is `[exe, "-p", "--output-format", "json", "--permission-mode", "bypassPermissions", (+ mcp flags)]`.
- `Popen(..., stdin=subprocess.PIPE, ...)`; `proc.communicate(input=prompt, timeout=timeout)`.
- Fast unit test `test_run_claude_headless_passes_prompt_via_stdin` (monkeypatched `Popen`) asserts the prompt is NOT an argv element and arrives as stdin input, and that `--output-format json` + mcp flags survive.

**Why:** a multi-line argv to `claude.CMD` is truncated by `cmd.exe` at the first newline, also dropping trailing flags -> claude runs in default text mode -> `json.loads` fails. Verified live (multi-line argv fails; multi-line stdin succeeds).

---

### Task B: review via inlined `review-pr` body + staged agents (NEW 2026-05-24 - TODO)

**Goal:** Make `_real_review` run the real four-role review loop headlessly WITHOUT a slash command: stage the four agent files into the worktree's `.claude/agents/`, then run the inlined `commands/review-pr.md` body (spec id substituted) as the prompt. Verdict still from `_verdict_from_graph`.

**Files:**
- Modify: `mcp-server/src/agentic_mcp/orchestrate.py` (`_real_review`; add a small staging helper; thread a `source_root` for the command/agent files)
- Test: `mcp-server/tests/test_orchestrate.py` (fast, claude monkeypatched)

**Background facts (from live + Claude Code docs):**
- Headless `claude -p` supports NO custom slash commands -> cannot invoke `/agentic:review-pr`.
- Headless `claude -p` DOES discover project-level `<cwd>/.claude/agents/*.md` (by `name:` frontmatter), so the Task tool can dispatch them. No flag needed.
- `commands/review-pr.md` is just an instruction prompt referencing `$1`/`$ARGUMENTS` for the spec id; inlining its body (with the id substituted) reproduces the loop engine.
- Source files live at the agentic repo root: `agents/{spec-checker,code-reviewer,contrarian,builder}.md` and `commands/review-pr.md`. Thread a `source_root` into `tick()`/`_real_review` (default: derive from the package location / repo root). For the e2e, the source_root is the repo under test.

**Acceptance Criteria:**
- [ ] `_real_review` stages the four agent files into `<worktree>/.claude/agents/` before running the review (creates the dir; copies the files).
- [ ] `_real_review` reads `commands/review-pr.md`, substitutes the spec id for `$1` and `$ARGUMENTS`, and passes the resulting body as the prompt to `run_claude_headless(body, cwd=<worktree>, mcp_config=<staged>, timeout=1800)`.
- [ ] Verdict still derived via `_verdict_from_graph(conn, spec_id)`; ANY exception (missing source files, claude crash/timeout, query error) -> NEEDS_FIXING; never raises.
- [ ] Fast unit tests (claude monkeypatched) assert: (a) the agent files are staged into `<worktree>/.claude/agents/`; (b) the prompt passed to `run_claude_headless` contains the review-pr body text with the spec id substituted and does NOT contain a literal `/agentic:review-pr`; (c) verdict CLEAN/NEEDS_FIXING per graph; (d) error -> NEEDS_FIXING.
- [ ] Existing `_real_review` fast tests updated to the new signature/behavior (they monkeypatch `run_claude_headless`, so they keep working; add the staging-dir assertions).

**Steps (TDD):**

- [ ] **Step 1: Write/adjust failing fast tests.** Extend `tests/test_orchestrate.py`'s `_real_review` tests: provide a `source_root` (a tmp dir containing `commands/review-pr.md` with a `$1` token and `agents/*.md` stubs), monkeypatch `run_claude_headless` to capture the prompt + cwd, and assert: agents staged into `<worktree>/.claude/agents/`; captured prompt contains the substituted spec id and the command body (not a slash command); CLEAN/NEEDS_FIXING from seeded findings; exception -> NEEDS_FIXING. Run -> expect FAIL.

- [ ] **Step 2: Implement.** In `orchestrate.py`:
  - Add `_stage_review_agents(source_root, worktree)`: `mkdir <worktree>/.claude/agents`; copy `source_root/agents/{spec-checker,code-reviewer,contrarian,builder}.md` into it.
  - Add `_review_prompt(source_root, spec_id)`: read `source_root/commands/review-pr.md`, `.replace("$ARGUMENTS", spec_id).replace("$1", spec_id)`, return the body.
  - Rewrite `_real_review(conn, task_id, job_result)`:
    ```python
    try:
        spec_id = relations.neighbors(conn, task_id, "implements", "out")[0]
        src = job_result.get("source_root") or _default_source_root()
        _stage_review_agents(src, job_result["worktree"])
        headless.run_claude_headless(
            _review_prompt(src, spec_id),
            cwd=job_result["worktree"],
            timeout=1800,
            mcp_config=job_result.get("mcp_config"),
        )
        return _verdict_from_graph(conn, spec_id)
    except Exception:  # noqa: BLE001 - never merge unreviewed code; never raise
        return {"verdict": "NEEDS_FIXING", "reviewer": "code-reviewer",
                "hit": True, "calibrate": False}
    ```
  - `_default_source_root()`: the repo root that ships `commands/`+`agents/` (derive from the package path, e.g. parents of `agentic_mcp.__file__`, or accept via `tick(..., source_root=...)`). Thread `source_root` from `tick()` into `job_result` (single-threaded review phase, like `mcp_config`/`worktree`).
  - `tick()`: inject `r["source_root"] = source_root` alongside `r["worktree"]`/`r["mcp_config"]` before `review_fn`; add `source_root=None` param (default `_default_source_root()`).

- [ ] **Step 3: Run fast tests + full fast suite.** `pytest -k real_review -v`, then `pytest -m "not llm" -q` (all green).

- [ ] **Step 4: Update Task 6 e2e** to pass `source_root` = the repo under test (which must contain `commands/review-pr.md` + `agents/*.md`; the e2e copies them in from the real repo, or points source_root at the real repo root). Re-run the live e2e -> expect the criterion marked satisfied + merge.

- [ ] **Step 5: Commit.**
```bash
git add mcp-server/src/agentic_mcp/orchestrate.py mcp-server/tests/test_orchestrate.py
git commit -m "feat(orchestrate): _real_review stages agents + inlines review-pr body (headless has no slash commands)"
```

**Open question for the e2e (resolve during Task 6 update):** the synthetic temp repo has no `commands/`+`agents/`. Either (a) point `source_root` at the real agentic repo root (the agents are repo-relative and self-contained), or (b) copy `commands/review-pr.md`+`agents/*.md` into the temp repo. Prefer (a) if the agent prompts don't assume repo-specific paths; else (b).

---

## Deferred / out of scope (from the spec, recorded so it is not silently dropped)

- **Repair-loop e2e (spec's optional second case):** "the first build fails spec-check and review-pr's fix loop repairs it, then merges." Deliberately NOT automated here: forcing a real model to fail a first round on purpose is non-deterministic and would make an `llm`-marked test flaky for no mechanism coverage gain (review-pr's inner fix loop is already exercised by the Phase 1 review-pr tests). The spec marks this "(if feasible within timeout budget)"; the determinism cost makes it not feasible as a reliable automated test. Run manually if desired.
- **Multi-task-per-spec review composition** — out of scope (spec). This plan assumes one task per spec as the reviewable unit, matching the Phase 2 e2e.
- **Real reviewer calibration** (ground-truth hit/miss at review time) — out of scope; `calibrate=False` everywhere in this plan.
- **Changing the four-role agent prompts or the review-pr loop logic** — out of scope.

## A note on the production `.mcp.json` side effect

When a real `--once` tick runs in a repo that has dispatched tasks AND a `db_path` (always true via `main()`), `stage_mcp_config` writes/overwrites `<repo>/.mcp.json` with a resolved config. That is the intended mechanism (headless workers need a resolved server command). In THIS repo a committed `.mcp.json` exists; a live orchestration run here would overwrite it with the resolved form. The e2e stages into a throwaway temp repo, so it is unaffected. Flagged, not changed — production orchestration is expected to run against a target repo, and the resolved config is what workers require.

## Self-review (run against the spec)

- **Spec coverage:** Component 1 `_real_launch` + `_build_builder_prompt` (Tasks 2, 3, 5); Component 2 `_real_review` + `_verdict_from_graph` (Tasks 1, 4); thread-safety constraint honored (prompt/verdict/staging all single-threaded in tick; Task 5); error/timeout safety -> NEEDS_FIXING (Task 4); MCP staging threaded via `db_path` (Task 5); calibrate=False everywhere; fast unit tests for both pure helpers (Tasks 1, 2); fast suite unchanged (Task 5 step 8); `llm`-marked e2e (Task 6). Verdict-scope finalized to `parent_id` (not `scope`) with the rationale documented.
- **Type consistency:** helper signatures `_build_builder_prompt(conn, task_id) -> str` and `_verdict_from_graph(conn, spec_id) -> dict` are used identically in `_real_review` and `tick()`. Job dict keys (`task_id`, `worktree`, `branch`, `prompt`, `mcp_config`) and launch-result keys (`task_id`, `ok`, `sha`, `worktree`, `error`) are consistent across Tasks 3, 4, 5, 6.
- **Placeholder scan:** every code step shows complete code; no TBD/TODO; verify commands are exact.

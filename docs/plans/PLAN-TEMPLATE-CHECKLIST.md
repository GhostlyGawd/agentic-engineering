# Plan-Template Checklist

> Run through this before declaring any Phase-N implementation plan ready to execute. Every item is a concrete gap caught during Phase 0 (see `docs/post-mortems/2026-05-17-phase-0.md`). Treat each as a yes/no audit, not a suggestion.

## 1. Precondition state (pre-Task-0)

- [ ] Is the working directory already a git repo? If not, Task 0 initializes one.
- [ ] Run `git status` against the actual working tree NOW (before the plan executes). Audit what `git add .` would sweep up:
  - [ ] Session/IDE metadata gitignored? (`.engineering-board/`, `.claude/sessions/*`, `.vscode/*`)
  - [ ] Local-only artifacts gitignored? (`.venv/`, `.agentic/graph.db`, `__pycache__/`, `*.pyc`)
  - [ ] No secrets, API tokens, or absolute Windows paths in any tracked file?
- [ ] External services authenticated for any task that needs them (`gh auth status`, `npm whoami`, etc.)?
- [ ] Required toolchain installed and version-confirmed (Python, Node, etc.)?

## 2. Acceptance-criteria language

- [ ] No exact test counts in any acceptance line. Phase 0 said "11 tests pass" and the suite was 12 — that reads as a regression on review. Use "suite green" / "pytest exits 0".
- [ ] No exit codes specified for `pytest --collect-only` — it returns 5 when zero tests are collected, not 0.
- [ ] Every criterion has either a runnable verify command (`pytest path/to/test.py::test_name`) OR a named runtime signal with a fix path. No "works correctly", no "handled appropriately".
- [ ] Feedback-loop field (Phase 1+): both an observable signal AND a fix path. "We'll watch the logs" rejects; "if X happens, open a bug and write a retro" accepts.

## 3. PowerShell 5.1 traps (Windows plans)

- [ ] Every `git commit -m "<heredoc>"` replaced with `git commit -F <tempfile>` (or `git commit -F -` with stdin). PSNativeCommandArgumentPassing word-splits heredoc bodies to native exes — Phase 0's first commit failed this way.
- [ ] The commit-message tempfile is written with `Set-Content -Encoding ascii` (NOT `-Encoding utf8`). PS5.1's `utf8` writes a UTF-8 BOM that `git commit -F` puts at the front of the commit subject — Phase 1's commit 7d2c0fe shipped a leading BOM (`﻿docs(plan):`) this way. ASCII commit messages need no BOM; for non-ASCII subjects use `git commit -F -` via stdin instead.
- [ ] Every `python -c "<sql>"` (or any native exe `-c "..."`) replaced with `python <tempfile>.py`. Same PSNativeCommand bug — embedded `"` get stripped. We've been bitten by this twice (build commits, SessionStart hook).
- [ ] No `2>&1` on any native exe call — corrupts `$?` and exit handling in PS5.1.
- [ ] `.ps1` string literals are ASCII-only inside `"..."`. No em-dash, smart quotes, right-arrow. Comments and `@"..."@` here-strings are safe.
- [ ] Every `.ps1` parse-checked before commit: `[Management.Automation.Language.Parser]::ParseFile($p,[ref]$null,[ref]$e); $e`.
- [ ] Any Python script that may print non-ASCII calls `sys.stdout.reconfigure(encoding="utf-8")` early in `main()` (cp1252 default on this machine).

## 4. Test design

- [ ] Validators and their tests draw input strings from the SAME fixture set. Phase 0's "users report" vs "user report" off-by-one happened because the validator's signal list and the test's input strings were authored separately.
- [ ] Timestamp-based assertions match the underlying resolution. If `_now()` truncates to seconds, the test's `sleep` is >= 1.1s and the assertion is `>=`, not `>`. Phase 0 had a flaky test from a 10ms sleep against second-resolution timestamps.
- [ ] Constraint tests verify failure for the RIGHT reason. A row violating both NOT NULL and CHECK raises `IntegrityError` from either — assert on the message, not the exception class.
- [ ] Subprocess-style tests (PowerShell-via-Python) cover every BRANCH of the script under test, not just happy paths. Phase 0's `test_walkup.py` missed the graph-stats-when-DB-exists branch and the bug surfaced on first real use.
- [ ] Every phase plan ships its own end-to-end exit-gate test exercising the new layer's full flow. Unit tests around it don't substitute. (Phase 0's `test_e2e_bootstrap.py` is the template.)

## 5. Process / commit hygiene

- [ ] One commit per task. Each commit reads cleanly in isolation.
- [ ] Each commit message names the task and references its acceptance criterion.
- [ ] Inline-fix policy: minor gaps (typo, missing import, off-by-one) fixed during execution AND noted in the commit message. Real gaps (missing step, wrong design) logged as `Bug`/`Retro` nodes; execution continues. No mid-plan re-architecture.
- [ ] `.tasks.json` sidecar maintained per task (status flipped to `completed` after commit). Cross-session resume depends on it.
- [ ] No CLAUDE.md created or edited. (Repo policy + PRD D-20.)

## 6. External dependencies

- [ ] MCP SDK version pinned in `pyproject.toml` after first round-trip passes (flexible during build, locked at exit).
- [ ] GitHub PAT scopes: fine-grained PATs need account-level `Administration: Write` for `gh repo create`; classic PATs with `repo` scope work without it. Pushing `.github/workflows/*.yml` needs `workflow` scope separately.
- [ ] GitHub push protection: defang fake credential fixtures (`AC` + 32 hex chars matches the Twilio SID regex even when synthetic).

## 7. Dogfood self-check (Phase 1+)

- [ ] The plan's own spec passes `validate_spec` from the agentic-engineering MCP server BEFORE the plan is written. If our own validator rejects our own spec, that's a Phase-0 gap to fix first — not a reason to bypass.
- [ ] The plan's `required_reads` field lists IDs of nodes that exist in `./.agentic/graph.db`.
- [ ] Any deviation from our own template/validator gets logged as a `SystemUsabilityBug` finding, not silently worked around. (PRD D-19.)

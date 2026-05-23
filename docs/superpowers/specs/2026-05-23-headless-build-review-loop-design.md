# Headless Build + Review Loop (design)

> Status: Approved (brainstorming) - ready for writing-plans.
> Date: 2026-05-23. Base branch: `main`. Work branch: TBD at plan time.
> Extends `2026-05-23-phase-2-orchestration-design.md`. Closes the autonomous
> build loop the phased rollout assumed but never gated (the rung between Phase 2
> and Phase 3).

## Purpose

Make the orchestrator's headless `tick()` actually build and actually review,
instead of dispatching a contentless builder prompt and rubber-stamping every
result CLEAN. Today:

- `_real_launch` sends every worker the same generic prompt ("implement the
  assigned task") with no task content and no graph read - workers build nothing
  meaningful.
- `_real_review` is a stub that returns `{"verdict": "CLEAN"}` unconditionally -
  nothing reviews the worker's code before it is merged.

This design replaces both seams with real implementations that reuse the
existing Phase-1 machinery (the `builder` agent and the `/agentic:review-pr`
four-role loop), keeping `tick()`'s structure, seam-injectability, and
never-raise contract intact.

## Architecture - the closed loop

`tick()` is unchanged in shape; only the two seam defaults become real:

```
tick() per claimed task (in its worktree):
  _real_launch  ->  claude -p <graph-assembled builder prompt>          -> commit
  _real_review  ->  claude -p "/agentic:review-pr <spec_id>"            -> fix-loop runs
                    verdict = (open Criticals for spec ? NEEDS_FIXING : CLEAN)
  CLEAN        -> git merge
  NEEDS_FIXING -> retry cap (reset to pending; escalate on 3rd strike)
  crash/timeout-> NEEDS_FIXING (never merge unreviewed code)
```

`/agentic:review-pr` is itself the full loop engine: spec-checker gate ->
code-reviewer + contrarian in parallel -> builder loop-fix (one commit per
iteration) -> re-loop until the blocker set empties (CLEAN) or diminishing
returns. So one headless review call runs the entire review-and-repair cycle and
lands on a terminal state. The orchestrator's per-task retry cap and review-pr's
inner fix loop are COMPLEMENTARY: inner = "repair this diff"; outer = "this task
keeps failing entirely -> escalate."

## Thread-safety constraint (shapes the design)

`headless.Pool` runs `launch_fn` in worker THREADS, and a `sqlite3.Connection` is
not safe to share across threads. Therefore:

- Anything needing the graph is computed in `tick()` itself (single-threaded, owns
  `conn`) BEFORE dispatch, and passed into the job dict.
- Worker threads (`_real_launch`) never touch `conn` - they only run `claude -p`
  with a pre-assembled prompt.
- `_real_review` runs in `tick()`'s single-threaded review phase, so it DOES
  receive `conn` and may query the graph directly.

## Component 1 - `_real_launch` (real builder)

**New pure helper** `_build_builder_prompt(conn, task_id) -> str`:
- Read the Task via `nodes.get_node(conn, task_id)` (its `body`).
- Resolve the parent Spec: `relations.neighbors(conn, task_id, "implements", "out")[0]`,
  then `nodes.get_node` it for `criteria_json`.
- Return a builder-role prompt that: names the task id and spec id, embeds the
  task body and the spec criteria (parsed from `criteria_json`), and instructs the
  worker to implement in the current worktree, self-verify against the criteria,
  and commit (NOT push). Concise; the embedded builder guidance mirrors
  `agents/builder.md`.
- Fast-unit-testable: assemble from a seeded graph, assert the prompt contains the
  task body and each criterion text. No `claude`.

**`tick()` job assembly (step 4) changes:** for each dispatched task, add to the
job dict:
- `"prompt": _build_builder_prompt(conn, tid)`
- `"mcp_config": <staged path>` (see below)

**`_real_launch(job)` change:** run `claude -p job["prompt"]` (via
`headless.run_claude_headless(job["prompt"], cwd=job["worktree"],
mcp_config=job["mcp_config"])`), then `git rev-parse HEAD`. Return shape unchanged:
`{"task_id", "ok": True, "sha"}` or `{"task_id", "ok": False, "error"}`. Still
catches its own exceptions (the Pool re-raises whatever launch_fn raises).

**MCP config staging:** once per tick, stage a resolved `.mcp.json` in the repo via
the existing `headless.stage_mcp_config(repo, db_path)` so each worker can reach
the `agentic-graph` server. `tick()` needs the DB path; thread it through (the CLI
`main()` already resolves it via `db.resolve_db_path()` - pass it into `tick()` as
an optional `db_path` param, defaulting to deriving from the connection / env).

## Component 2 - `_real_review` (real reviewer)

**`review_fn(conn, task_id, job_result)`** (already receives `conn`):
- Resolve the spec: `relations.neighbors(conn, task_id, "implements", "out")[0]`.
- Run `claude -p "/agentic:review-pr <spec_id>"` in the task's worktree with the
  staged `mcp_config`. The worktree path is provided by `tick()` (added to
  `job_result`, since the launch result currently carries only `task_id/ok/sha`).
  review-pr auto-detects "branch ahead of main" and reviews the worktree branch's
  diff.
- **New pure helper** `_verdict_from_graph(conn, spec_id) -> dict`: query open
  Critical findings scoped to the spec
  (`query_graph(type="Finding", severity="Critical", status="open", scope=<spec scope>)`,
  or the equivalent direct SELECT). ANY open Critical -> `NEEDS_FIXING`, else
  `CLEAN`. Returns `{"verdict", "reviewer": "code-reviewer", "hit": True,
  "calibrate": False}`. Fast-unit-testable: seed findings, assert verdict.
- **Error/timeout safety:** `_real_review` wraps the `claude -p` call in
  try/except. On ANY failure (review-pr timing out under the headless timeout,
  crashing, non-zero exit), return `{"verdict": "NEEDS_FIXING", "reviewer":
  "code-reviewer", "hit": True, "calibrate": False}` - never merge unreviewed
  code; let the retry cap terminate a persistently unreviewable task. This keeps
  tick()'s never-raise contract (the review phase has no outer try/except).

**Calibration:** `calibrate: False` for now. At review time there is no ground
truth for whether the verdict was correct, so the headless reviewer must not bias
per-role calibration. Real reviewer calibration is a noted future item.

## Verdict-scope detail

Findings logged by review-pr carry `scope` (inherited from the spec) and/or
`parent_id`. `_verdict_from_graph` keys off the SPEC's scope. The exact query
(scope match vs. parent_id walk) is finalized in the plan against the real
finding rows review-pr produces; the contract is "open Critical for this spec ->
NEEDS_FIXING."

## Assumptions & limitations (explicit)

- **One task per spec** as the reviewable unit. review-pr checks the whole spec's
  criteria, so this first version assumes the spec's reviewable diff is one task's
  worktree branch - exactly what the Phase 2 e2e models (spec_a -> task_a).
  Multi-task-per-spec review composition is deferred.
- **Live-only execution.** Real launch/review run only when the `claude` CLI is
  present. The fast suite keeps stubbing all four seams; existing tests are
  unchanged. New end-to-end behavior is verified by an `llm`-marked e2e.
- **Trust boundary.** Workers run `--permission-mode bypassPermissions` inside
  their worktree (unchanged from today's e2e). Noted, not altered.
- **Benefits from but does not hard-require the Phase 2.1 retry cap.**
  Escalation-after-3 makes a stuck review terminate cleanly; without it a stuck
  task re-dispatches every tick (today's behavior). Recommended to land the retry
  cap first (or together).
- **Cost/latency.** Each task now spawns two real `claude -p` sessions (build,
  then a multi-round review). Slow and subscription-metered; acceptable because it
  is the real work and is exercised only in `llm`-marked tests, never the fast
  suite.

## Testing

- **Fast suite unchanged.** All seams still stubbed in `test_orchestrate.py`;
  existing cases stay green.
- **New fast unit tests** for the two pure helpers:
  - `_build_builder_prompt`: prompt contains the task body and each criterion text.
  - `_verdict_from_graph`: an open Critical scoped to the spec -> NEEDS_FIXING; none
    -> CLEAN.
- **New `llm`-marked e2e** (extends `test_phase2_e2e.py` patterns): a dispatched
  Spec + Task where a real builder builds and real review-pr gates it to CLEAN ->
  task merged + criteria satisfied. Second case (if feasible within timeout
  budget): the first build fails spec-check and review-pr's fix loop repairs it,
  then merges. Deselected under `-m "not llm"`; skipif `claude` not on PATH.

## Out of scope

- Multi-task-per-spec review composition.
- Real reviewer calibration (ground-truth signal for hit/miss).
- Changing the four-role agent prompts or the review-pr loop logic itself.
- The Phase 2.1 hardening items (separate spec); the retry cap is a recommended
  companion, not part of this spec.

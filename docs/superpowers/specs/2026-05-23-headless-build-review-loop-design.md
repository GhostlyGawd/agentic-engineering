# Headless Build + Review Loop (design)

> Status: Approved (brainstorming); REVISED 2026-05-24 after live e2e exposed two
> wrong assumptions (see "Revision 2026-05-24" below).
> Date: 2026-05-23. Base branch: `main`. Work branch: `feat/headless-build-review-loop`.
> Extends `2026-05-23-phase-2-orchestration-design.md`. Closes the autonomous
> build loop the phased rollout assumed but never gated (the rung between Phase 2
> and Phase 3).

## Revision 2026-05-24 (live-validated corrections)

The first live `llm`-marked e2e run surfaced two facts that invalidate parts of
the original design. Both were invisible to the fast suite (which stubs/monkeypatches
every `claude` call) and only appear when a real `claude -p` runs.

1. **Prompt delivery (build seam): pass the prompt via STDIN, not as a `-p` argv.**
   On Windows `claude` resolves to `claude.CMD` (a batch shim). A MULTI-LINE prompt
   passed as a `-p <prompt>` argv is truncated by `cmd.exe` at the first newline,
   which ALSO drops every flag positioned after it (including `--output-format json`)
   -> `claude` runs in default text mode on a one-line prompt -> the JSON parse fails.
   The graph-assembled builder prompt is multi-line, so every real build failed.
   Fix (landed): `headless.run_claude_headless` feeds the prompt over stdin (`claude -p`
   reads stdin when no positional prompt is given). Newline-safe; verified live.

2. **Review seam: `claude -p "/agentic:review-pr <spec_id>"` is INFEASIBLE.**
   Headless/print mode supports NO custom slash commands - not plugin-namespaced
   (`/agentic:review-pr`), not project-level. Confirmed live ("Unknown command:
   /agentic:review-pr") and in the Claude Code docs ("User-invoked skills ... and
   built-in commands are only available in interactive mode. In `-p` mode, describe
   the task you want to accomplish instead."). Installing the plugin would NOT help;
   the slash-command parser is simply inactive in `-p`. The original locked decision
   #2 is therefore replaced (see the revised Component 2 below):

   **Revised review approach (inline body + staged agents).** `_real_review`:
   - Stages the four agent definition files (`agents/spec-checker.md`,
     `code-reviewer.md`, `contrarian.md`, `builder.md`) into
     `<worktree>/.claude/agents/`. Project-level `.claude/agents/*.md` ARE discovered
     by a headless `claude -p` run (no flag needed), so the Task tool can dispatch
     them by name. This carries the review machinery into the throwaway worktree
     without depending on the plugin being installed in the host environment.
   - Reads the `commands/review-pr.md` BODY (it is just an instruction prompt),
     substitutes the spec id for `$1`/`$ARGUMENTS`, and passes THAT as the `-p`
     prompt (over stdin). The inlined body is the same four-role loop engine; it
     dispatches the staged subagents via the Task tool. Main-thread -> subagent
     dispatch is one level deep (the documented "subagents don't nest" limit does
     not bite).
   - Verdict still derived from the graph via `_verdict_from_graph` (unchanged):
     any open Critical for the spec -> NEEDS_FIXING, else CLEAN.
   - `_real_review` must locate the SOURCE command/agent files. In production the
     orchestrator runs inside the agentic repo, so they are at the repo root
     (`commands/`, `agents/`); thread that source root in (default: derive from the
     package/repo location). For the e2e, stage from the repo under test.
   - Still wrapped in try/except -> NEEDS_FIXING on any failure; never raises.

   Everything else about the review (graph-derived verdict, calibrate=False,
   error->NEEDS_FIXING, one-task-per-spec) is unchanged.

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
  _real_launch  ->  claude -p <graph-assembled builder prompt>  (via STDIN)   -> commit
  _real_review  ->  stage agents/*.md into <worktree>/.claude/agents/;
                    claude -p <inlined review-pr.md body, spec_id substituted> (STDIN) -> fix-loop runs
                    verdict = (open Criticals for spec ? NEEDS_FIXING : CLEAN)
  CLEAN        -> git merge
  NEEDS_FIXING -> retry cap (reset to pending; escalate on 3rd strike)
  crash/timeout-> NEEDS_FIXING (never merge unreviewed code)
```

> NOTE (2026-05-24): the original `claude -p "/agentic:review-pr <spec_id>"` is
> infeasible - headless `-p` has no custom slash commands. The inlined-body +
> staged-agents approach above replaces it; see "Revision 2026-05-24". The prompt
> for BOTH seams is delivered over stdin (Windows `.CMD` multiline-argv truncation).

The inlined `review-pr` body is itself the full loop engine: spec-checker gate ->
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

**`_real_launch(job)` change:** run the prompt (via
`headless.run_claude_headless(job["prompt"], cwd=job["worktree"],
mcp_config=job.get("mcp_config"))`), then `git rev-parse HEAD`. Returns
`{"task_id", "ok": True, "sha", "worktree"}` (worktree carried forward for the
review phase) or `{"task_id", "ok": False, "error"}`. Still catches its own
exceptions (the Pool re-raises whatever launch_fn raises).

> NOTE (2026-05-24): `run_claude_headless` delivers the prompt over STDIN, not as a
> `-p` argv. The multi-line builder prompt would otherwise be truncated by the
> Windows `claude.CMD` shim (see "Revision 2026-05-24"). This is a fix inside the
> shared headless wrapper, so it benefits both the build and review seams.

**MCP config staging:** once per tick, stage a resolved `.mcp.json` in the repo via
the existing `headless.stage_mcp_config(repo, db_path)` so each worker can reach
the `agentic-graph` server. `tick()` needs the DB path; thread it through (the CLI
`main()` already resolves it via `db.resolve_db_path()` - pass it into `tick()` as
an optional `db_path` param, defaulting to deriving from the connection / env).

## Component 2 - `_real_review` (real reviewer)

> REVISED 2026-05-24. The original "run `claude -p '/agentic:review-pr <spec_id>'`"
> bullet is INFEASIBLE (headless has no custom slash commands). Replaced by the
> inline-body + staged-agents approach below. See "Revision 2026-05-24".

**`review_fn(conn, task_id, job_result)`** (already receives `conn`):
- Resolve the spec: `relations.neighbors(conn, task_id, "implements", "out")[0]`.
- **Stage the review agents:** copy the four agent definitions
  (`spec-checker.md`, `code-reviewer.md`, `contrarian.md`, `builder.md`) from the
  source root into `<worktree>/.claude/agents/`. A headless `claude -p` run
  discovers project-level `.claude/agents/*.md`, so the inlined loop can dispatch
  them by name via the Task tool - without the agentic plugin being installed in
  the host environment. The source root (where `commands/` + `agents/` live) is
  threaded in (default: derived from the package/repo location).
- **Run the inlined review loop:** read `commands/review-pr.md`'s BODY, substitute
  the spec id for `$1`/`$ARGUMENTS`, and pass that as the prompt to
  `headless.run_claude_headless(<body>, cwd=<worktree>, mcp_config=<staged>,
  timeout=1800)` (prompt delivered over stdin). The body is the same four-role loop
  engine and auto-detects "branch ahead of main" to review the worktree diff. The
  worktree path is provided by `tick()` (added to `job_result`; the launch result
  carries `task_id/ok/sha/worktree`).
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

FINALIZED (implemented): `_verdict_from_graph` keys off `parent_id`, NOT `scope`.
Both spec-checker and code-reviewer log findings with `log_finding(parent_id=<spec_id>, ...)`,
and a spec's `scope` is frequently `None` (which would collide across every
scope-less spec). `query_graph` has no `parent_id` filter, so a direct SELECT is
used: `SELECT COUNT(*) FROM finding WHERE parent_id=? AND severity='Critical' AND
status='open'`. The contract is "open Critical for this spec -> NEEDS_FIXING".

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
  - `_verdict_from_graph`: an open Critical for the spec (`parent_id`) -> NEEDS_FIXING;
    none -> CLEAN.
- **New fast unit test (added 2026-05-24)** for the headless prompt-delivery contract:
  `run_claude_headless` passes the prompt via stdin, never as a `-p` argv (monkeypatched
  `Popen`; asserts the multi-line prompt is not an argv element and arrives as stdin input).
- **New `llm`-marked e2e** (extends `test_phase2_e2e.py` patterns): a dispatched
  Spec + Task where a real builder builds and the REAL inlined review loop (staged
  agents + inlined `review-pr` body, NOT a slash command) gates it to CLEAN -> task
  merged + criterion satisfied (the criterion-satisfied assertion is load-bearing:
  it proves the spec-checker actually ran). Deselected under `-m "not llm"`; skipif
  `claude` not on PATH.
  - The e2e must stage the four agent files into the worktree's `.claude/agents/`
    (the orchestrator does this in `_real_review`), so the headless run can dispatch
    them. The synthetic temp repo otherwise has no command/agent context.
- **Second e2e case (deferred):** "first build fails spec-check, fix loop repairs,
  then merges" - deferred as non-deterministic with a real model (the spec's
  "if feasible" caveat; the inner fix loop is covered by Phase 1 review-pr tests).

## Out of scope

- Multi-task-per-spec review composition.
- Real reviewer calibration (ground-truth signal for hit/miss).
- Changing the four-role agent prompts or the review-pr loop logic itself.
- The Phase 2.1 hardening items (separate spec); the retry cap is a recommended
  companion, not part of this spec.

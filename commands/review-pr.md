---
description: Run the autonomous review loop on the current change set. Auto-detects the target (open PR, else branch-vs-main, else working tree). Gate-then-parallel review, four-tier severity, auto-triaged Importants, a critical loop with a 3-iteration diagnostic and stopping rules, then closes with Retros and a Strength.
argument-hint: "[spec_id]"
---

You are the loop engine. Loop CONTROL lives here on the Claude side; loop STATE
lives in the MCP graph (design section 3). Drive it explicitly.

## Step 0 - Detect the target (L-10)

In order, take the first that applies:
1. An open PR for this branch: `gh pr view --json number,headRefName` succeeds ->
   review the PR diff.
2. Else a branch ahead of main: `git rev-parse --abbrev-ref HEAD` is not `main`
   and `git diff main...HEAD` is non-empty -> review that diff.
3. Else the working tree: review `git diff HEAD` (uncommitted changes).
Resolve the Spec: use `$1` if given, else the most recently dispatched Spec in
scope (`query_graph(type='Spec', status='dispatched')`).

## Step 1 - One review round (gate-then-parallel, L-7)

1. Dispatch the `spec-checker` subagent (Task tool) FIRST. It is the gate: it
   runs each criterion's verify and logs a Critical per failure.
2. If the spec-checker logged ANY open Critical, the gate failed - skip the
   judgment agents this round (no point reviewing taste on broken code). Go to
   Step 2.
3. If the gate passed, dispatch `code-reviewer` AND `contrarian` IN PARALLEL
   (two Task calls in one message), each blind to the other. They log findings
   with severity; the code-reviewer also calls `record_triage` for every
   Important.

## Step 2 - Classify and triage

- Collect this round's open findings: `query_graph(type='Finding', status='open', scope=<scope>)`.
- The BLOCKER SET = open Criticals PLUS Importants whose `triage` is `fix-in-pr`.
- `backlog` Importants are logged non-blocking; they persist with their link so
  a later Critical can trace `caused-by` them.
- Suggested and Strength never block.

## Step 3 - Stopping rules (check BEFORE fixing)

- **Primary exit:** the blocker set is empty -> the loop is done. Go to Step 6.
- **Diminishing returns:** this round found zero NEW Criticals versus the prior
  round and regressed none of the prior approvals -> the floor is reached ->
  close even if Suggested/backlog Importants remain. Go to Step 6.
- Otherwise there is at least one open blocker -> Step 4.

## Step 4 - Critical loop bookkeeping + diagnostic

For each open Critical:
- If it has no `CriticalLoop` yet, `start_critical_loop(finding_id=<id>)`.
- If it already has one and this is a new round on the SAME critical,
  `advance_critical_loop(loop_id=<id>)`. That call fires the diagnostic flag
  when the count reaches 3.
- If `advance_critical_loop` returns a row with `diagnostic_fired_at` set, the
  same critical has survived three iterations: surface a NON-BLOCKING diagnostic
  to the user with hypotheses ("the spec may be wrong, not the code"; "the
  approach may be architecturally unsuitable"). The loop CONTINUES - the
  diagnostic informs the next fix, it does not stop the loop.

Also run the stability check (Task 17): for each newly-flagged file, call the
stability tool to detect a contradiction-of-prior-approval and log a soft
`Pattern` if found. This never suppresses the critical - it only records a
calibration signal.

## Step 5 - Fix and re-loop (L-11: one commit per iteration)

Dispatch the `builder` subagent in loop-fix mode against the blocker set. When
it returns, make exactly ONE commit for this iteration, with trailers:

```
Loop-Id: <loop_id>
Loop-Iteration: <n>
```

Then go back to Step 1 for the next round.

## Step 6 - Close the loop

- For each resolved Critical, `resolve_critical_loop(loop_id=<id>)` and write a
  `log_retro(body=..., failed_layer=<spec|implementation|review|unknowable>,
  caused_by_finding_id=<finding_id>)`.
- Log one `Strength` finding summarizing what held up (calibration + stability
  baseline for the next review).
- Leave `backlog` Importants open and linked; report them to the user as
  deferred, not lost.
- Report: rounds run, criticals resolved, diagnostics fired, Patterns recorded,
  backlog carried.

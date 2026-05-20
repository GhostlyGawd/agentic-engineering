# Phase 1 Design: Build Pipeline + Review Loop

**Date:** 2026-05-20
**Status:** Design locked via brainstorm. Ready for `validate_spec` dogfood gate, then writing-plans.
**Author:** GhostlyGawd + Claude (brainstorm session "sp 03")
**Upstream:** `agentic-engineering-system-prd-v3.md` (Phase 1: Build Pipeline + Per-PR Review Pipeline)
**Predecessor:** Phase 0 shipped at commit cbbd328 (66/66 tests green).

> This is the design artifact (brainstorm output), not the executable plan. The plan is written next via `superpowers-extended-cc:writing-plans`, applying `docs/plans/PLAN-TEMPLATE-CHECKLIST.md` throughout.

---

## 1. Scope & falsifier

Phase 1 ships the full PRD Phase 1: four-role team, four-tier severity, autonomous critical-loop with no hard cap, 3-iteration non-blocking diagnostic, stopping rules, layer-tagged Retros, spec-writer subagent, two new commands.

**Falsifier (locked):** the exit-gate test demonstrates, with real agents, all of:
1. A 1-critical resolution (planted bug → flagged → fixed → re-verified → Retro tagged).
2. A stubborn-critical that fires the 3-iteration diagnostic and resolves on iteration 4.
3. A mixed-severity round (Critical + Important + Suggested + Strength) with auto-triaged importants.
4. The contrarian catching a flaw the reviewer missed.

This is NOT a smaller cut — it is the full PRD Phase 1.

## 2. Locked decisions

| # | Decision | Choice |
|---|---|---|
| L-1 | Phase 1 falsifier | All four scenarios combined (full PRD scope) |
| L-2 | Critical-loop persistence | New `CriticalLoop` entity, linked to Finding via `tracks` |
| L-3 | `failed_layer` storage | Enum-constrained column on Retro (spec/implementation/review/unknowable) |
| L-4 | Spec-writer role | Wrap-as-callable: reads `skills/spec-writing/SKILL.md`, runs Socratic pass, calls `validate_spec` inline, loops until pass, retry-cap guard |
| L-5 | Criterion identity | Integer indices + `dispatched_at` immutability + `supersedes` for genuine changes |
| L-6 | Exit-gate test mechanism | Pre-staged artifacts + real agents via **headless `claude` CLI** (not API) |
| L-7 | Agent invocation order | Gate-then-parallel: spec-checker first; if it passes, code-reviewer + contrarian run in parallel, blind to each other |
| L-8 | Builder loop behavior | One agent, dual mode (Option A): `agents/builder.md` gains a loop-fix section |
| L-9 | Importants triage | Auto-apply reviewer's fix-in-PR/backlog recommendation; no human-in-loop; preserve traceability |
| L-10 | `/agentic:review-pr` target | Auto-detect: open PR (gh) → branch diff vs main → working tree vs HEAD |
| L-11 | Commit semantics | One commit per iteration, carrying loop_id + iteration number |

**Guiding principle (user-stated):** the system triages and self-corrects autonomously. When it mis-triages, the system catches it through its own feedback machinery (Retro + `failed_layer=review` + Phase 4 calibration), NOT through a human checkpoint. Self-correction is a system property, not a babysitting task.

## 3. Architecture: control vs state

Hard constraint: **an MCP server cannot dispatch Claude subagents** (subagents are a Claude Code construct via the Task tool). Therefore:

- **Loop control flow** (re-run-review-until-no-blockers, dispatching builder/reviewer/contrarian) lives on the **Claude side** — in the `/agentic:review-pr` command instructions, executed by the session.
- **Loop state** (CriticalLoop rows, findings, iteration counts, triage decisions) lives in the **MCP server** as graph nodes + tools.

The MCP server is memory; the command is the engine. Matches Phase 0's split.

## 4. Schema changes (logical — exact DDL conforms to Phase 0's `mcp-server/src/agentic_mcp/schema.sql`, read at plan-time)

> **Phase 0 reality correction (verified against source 2026-05-20):** `failed_layer` is **already shipped** — `retro` table has the exact enum CHECK (`schema.sql:181-194`), `create_node` accepts it (`nodes.py:39` EXTRA_OPTIONAL), and `agents/builder.md` already instructs writing it. Phase 1 needs only the `log_retro` convenience wrapper, NOT a schema migration for it. Also note: there is **no single `nodes` table** — each entity type has its own table; a new entity = a new table + an `ENTITY_TABLES` registration in `nodes.py`. The `relations` CHECK list (`schema.sql:213-216`) does **not** include `tracks`; adding the CriticalLoop→Finding `tracks` relation requires extending that CHECK.

| Change | Where | Detail |
|---|---|---|
| New entity `CriticalLoop` | new `critical_loop` table + `ENTITY_TABLES` | `finding_id`, `iteration_count`, `status` (open/resolved/escalated), `started_at`, `diagnostic_fired_at` (nullable), `resolved_at` (nullable). Linked to its Finding via `tracks` relation. |
| ~~New column `failed_layer`~~ | Retro | **ALREADY EXISTS in Phase 0.** No migration. Phase 1 adds only `log_retro` wrapper. |
| Extend `relations` CHECK | `relations` table | add `tracks` to the allowed relation_type set |
| New column `dispatched_at` | Spec | timestamp, NULL until `/agentic:dispatch`; drives criteria immutability |
| New column `criterion_index` | Finding | integer, NULL when not criterion-specific; links finding → criterion |
| New column `loop_iteration` | Finding | integer, NULL when not loop-attached; lets stopping rules compare round N vs N+1 |
| New column `triage` | Finding | enum (`fix-in-pr`, `backlog`), NULL unless severity=Important |

Migrations must be ordered and idempotent against an existing Phase 0 `graph.db`. (Phase 0 has no migration framework yet — plan-writing decides: additive `ALTER TABLE` script vs schema-version table. The dogfood graph at `./.agentic/graph.db` is a real upgrade target.)

## 5. New MCP tools

- `dispatch_spec(spec_id)` → sets `dispatched_at`; first action of `/agentic:dispatch`
- `validate_spec` (extend) → if spec already dispatched, reject any criteria change with the supersede instruction
- `start_critical_loop(finding_id)` → creates CriticalLoop, returns loop_id
- `advance_critical_loop(loop_id)` → increments iteration_count; sets `diagnostic_fired_at` when count hits 3
- `resolve_critical_loop(loop_id)` → status=resolved
- `get_open_loops(scope?)` → active loops, for cross-session resume
- `record_triage(finding_id, decision)` → sets Finding.triage
- `log_retro(body, failed_layer, caused_by_finding_id?)` → Retro with enum tag + optional causal link

## 6. Loop state machine

```
dispatch -> [iteration N] -> review round -> classify findings
                                                 |
              +----------------------------------+
              | open blockers (criticals +       | zero open blockers
              | fix-in-PR importants) remain     | (diminishing returns at floor)
              v                                  v
        builder loop-fix                     loop closes:
        (Option A dual mode)                 - Strength finding logged
        commit (1 per iteration,             - Retros for resolved criticals
         carries loop_id + iter#)              w/ failed_layer
              |                               - backlog importants persist
              v
        advance_critical_loop
              |
        iter==3 on same critical?
              | yes -> diagnostic fires (non-blocking,
              |        hypotheses surfaced), LOOP CONTINUES
              v
        next review round
```

Per round, agents fire gate-then-parallel (L-7): spec-checker first; if pass, code-reviewer + contrarian in parallel, blind to each other.

## 7. Severity classification + triage

- **Critical** → always blocks. Gets a CriticalLoop.
- **Important** → reviewer attaches `fix-in-pr` or `backlog`. System auto-applies (L-9). fix-in-pr blocks this round like a critical; backlog is logged non-blocking with link preserved so a later Critical can trace back via `caused-by` + `failed_layer=review`.
- **Suggested** → logged only. Never blocks.
- **Strength** → logged for calibration.

## 8. Stopping rules + diagnostic + stability check

- **Primary exit:** a full review round produces zero open blockers (no open criticals, no open fix-in-pr importants). Loop closes.
- **Diminishing returns:** a round finds zero *new* criticals and no regression of prior approvals → floor reached → close even if Suggesteds / backlog importants remain.
- **3-iteration diagnostic:** if the *same* critical (matched by `criterion_index` or root-cause tag) is still open after 3 iterations, fire a non-blocking diagnostic surfacing hypotheses ("spec may be wrong, not implementation"; "approach may be architecturally unsuitable"). **Loop continues.**

### Stability check (CORRECTED — see §12 rationale)

The instability signal is **NOT** "critical on an unchanged file" — that wrongly punishes genuine late discovery. The signal is **contradiction of a prior explicit approval**:

- Round N: reviewer said *nothing* about file X → round N+1 flags X → **late discovery, legitimate. Not instability.**
- Round N: reviewer logged a **Strength** on X or explicitly marked it clean → round N+1 flags X as critical on byte-identical code → **contradiction. Instability signal.**
- Round N: reviewer flagged X as Important/backlog → round N+1 escalates to Critical → **escalation, not contradiction. Not instability.**

Mechanically detectable: one commit per iteration (L-11), so diff X's git blob between round N and N+1 commits; unchanged blob + prior explicit approval = contradiction.

**Action (corrected):** (i) the critical is **always actioned, never suppressed** — it might be real; (ii) log a *soft* `Pattern` recording the contradiction as a calibration signal, surfaced to the user as a flag. Phase 1 **detects and records**; the "distrust this reviewer" verdict is deferred to Phase 4 calibration, which has the cross-round data to tell flip-flopping from genuine improvement. No punitive auto-suppression in Phase 1.

## 9. Agent roster

| Agent | File | Status |
|---|---|---|
| Builder | `agents/builder.md` | **updated** — Option A dual-mode (loop-fix section) |
| Spec-checker | `agents/spec-checker.md` | unchanged from Phase 0 (still the gate) |
| Code-reviewer | `agents/code-reviewer.md` | **new** — judgment findings + severity + triage recommendation |
| Contrarian | `agents/contrarian.md` | **new** — asymmetric prompt: find why the work is wrong |
| Spec-writer | `agents/spec-writer.md` | **new** — L-4: reads spec-writing SKILL, Socratic pass, validate_spec inline, retry-cap guard |

Tactical guidance stays embedded + concise. **Prompt-bloat budget:** soft target ~2500 tokens/agent; if exceeded, refactor deep conventions into `skills/reviewing/SKILL.md` read on demand (same pattern as spec-writer↔spec-writing). Measured during plan execution per PRD Open Question #10.

## 10. Commands

- `/agentic:dispatch <spec>` → validates, sets `dispatched_at`, kicks builder for iteration 1
- `/agentic:review-pr` → auto-detects target (open PR via gh → branch diff vs main → working tree vs HEAD), runs the loop
- `/agentic:new-spec` → invokes the spec-writer subagent (small addition; final inclusion decided at plan-time)

## 11. Exit-gate test (CORRECTED — headless `claude` CLI, NOT API)

The system runs on the Claude Max subscription (PRD Gating-2: "no network dependency, zero hosting cost"). The exit-gate test therefore uses **real Claude Code in headless mode**, not metered API calls:

- The test shells out to `claude -p "<prompt>" --output-format json` from a pytest subprocess — the **same subprocess pattern Phase 0 already uses** for PowerShell in `test_walkup.py`. Subprocessing `claude` instead of `powershell`.
- This dispatches the **real subagents** from `agents/*.md` through Claude Code's real dispatch path — so production and test exercise the *same* code path (no test/reality gap, unlike an API approach which would re-host the prompt differently).
- Agent `.md` files are the single source of truth; nobody strips frontmatter or re-hosts.
- Fixture: a working dir with `.agentic/` initialized and the plugin available; stage `iter1..iter4` artifacts; swap the next in per iteration (standing in for the builder); invoke `claude -p` per review round.
- **Assert at the loop level** (critical found, iteration advanced, diagnostic fired at 3, loop closed at 4, Retro tagged `implementation`) — never on exact finding text (non-deterministic).
- Gate behind a marker (`@pytest.mark.llm`) so the fast unit suite stays quick and Claude-session-free; the slow real-agent gate runs on demand.

**Cost framing (corrected):** under the Max subscription the marginal dollar cost is zero. Real costs are subscription quota/rate-limit consumption + wall-clock latency. L-7 (gate-then-parallel) still wins on those axes — fewer LLM calls on gate-failing iterations.

**Known risk:** "contrarian catches what the reviewer missed" is inherently flaky with real agents. Mitigation: stage that scenario's artifact with a flaw of a *type the contrarian's prompt specifically targets* (architectural/assumption flaw, not a line-level bug). Least deterministic part of the gate; revisit at plan-time.

## 12. Dogfood approach (Gating-4)

Phase 1 is built **using Phase 0**: this design's Spec (§13) passes through `validate_spec` before plan-writing — if rejected, that's a Phase 0 gap to fix first, not a reason to bypass. Phase 0's builder + spec-checker build Phase 1's pieces. Any temptation to bypass our own tools is logged as a `SystemUsabilityBug`.

## 13. Phase 1 Spec (for the `validate_spec` dogfood gate)

**Scope:** `mcp-server/`, `agents/`, `commands/`, `skills/` in the agentic-engineering plugin repo.

**Feedback loop:** If a Phase 1 review loop ships a wrong verdict in real use, the failure surfaces as a failing regression test or a user report; we open a Retro tagged by failed_layer and fix the agent prompt or stopping rule that caused it.

**Acceptance criteria:** (each with a runnable verify; test file names are provisional, finalized at plan-time)

1. CriticalLoop entity + Phase 1 schema migrations apply cleanly to an existing graph.db. — verify: `pytest mcp-server/tests/test_schema_phase1.py -q`
2. Critical-loop persistence tools (start/advance/resolve/get_open_loops) round-trip across a fresh DB connection. — verify: `pytest mcp-server/tests/test_critical_loop.py -q`
3. `failed_layer` enum rejects out-of-set values and accepts the four valid ones. — verify: `pytest mcp-server/tests/test_retro_layer.py -q`
4. `dispatched_at` immutability rejects post-dispatch criteria edits and points at supersede. — verify: `pytest mcp-server/tests/test_dispatch_immutability.py -q`
5. Spec-writer subagent calls validate_spec inline and refuses to return a rejected spec. — verify: `pytest mcp-server/tests/test_spec_writer.py -q`
6. Exit-gate e2e: stubborn-critical fires the diagnostic at iteration 3 and resolves at iteration 4. — verify: `pytest mcp-server/tests/test_phase1_e2e.py -m llm -q`
7. Mixed-severity round auto-triages importants per reviewer recommendation. — verify: `pytest mcp-server/tests/test_phase1_e2e.py::test_mixed_severity -m llm -q`
8. Stability check logs a Pattern on contradiction-of-prior-approval and stays silent on late discovery. — verify: `pytest mcp-server/tests/test_stability_check.py -q`

## 14. Deferred to plan-writing (not blocking)

- Exact DDL + migration strategy against Phase 0's real schema
- Planted-bug content for each exit-gate scenario (4 staged artifacts; Phase 0 used `slugify`)
- Contrarian prompt wording (the asymmetry that makes it catch distinct things)
- Whether `/agentic:new-spec` ships in Phase 1 or waits
- Final builder-loop file decision (Option A default; split to a second agent is a mechanical refactor if the prompt bloats)
- Apply every section of `PLAN-TEMPLATE-CHECKLIST.md`

## 15. Open risks

- Contrarian-catches assertion flakiness (§11).
- Prompt bloat across 5 agents (§9) — PRD Open Question #10.
- Migration against the live dogfood graph.db (§4).
- Headless `claude` invocation shape in tests needs a spike at plan-time (exact flags, output parsing, auth in the test env).

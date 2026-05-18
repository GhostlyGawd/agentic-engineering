# Falsificationist Review: norns-loop

## What the project predicts if it's working

The implicit central prediction (CHARTER.md:4-9, README.md:3): three autonomous Claude sessions, coordinating only through a filesystem queue and dispatched OMC subagents, will deliver, in order, M1..M6 — each milestone closed by a sealed-eval PASS authored by the Critic and never seen by the Builder. The visible signal of "working" is a monotonically advancing roadmap with `[critic-approved]` commits, sealed `eval_0N` passing, append-only test counts rising, zero `CHARTER_VIOLATION.md`, and `frames/` accumulating non-trivial output. The visible signal of "not working" should be: a milestone that cannot be closed despite repeated recovery proposals, sealed evals failing with no path forward, or a charter-hash trip. As we will see, every one of those "not working" signals has been pre-equipped with an absorption mechanism that prevents it from ever being final.

---

## Falsifiable predictions

1. **Charter hash trip halts the loop.** `CHARTER.md:39` / `orchestrator.py:89-103`. Falsifier: mutate one byte of `CHARTER.md` while the orchestrator runs; observe whether `CHARTER_VIOLATION.md` appears and `sys.exit(2)` fires. The plan describes the code but I see **no scheduled drill / chaos test** that exercises this on the live loop. The hash check exists; the alarm-actually-trips claim is untested in repo evidence.

2. **Append-only test rule is enforced by `.sealed/test-hashes.json` via `scripts/githooks/pre-commit:27-55`.** Falsifier: stage a one-line modification to an existing `tests/test_world_tick.py` and attempt commit; observe rejection. **Problem:** `Glob D:\...\.sealed\**` returned no files in the inspected worktree (.sealed/ is intentionally Critic-only and gitignored), and `pre-commit:27` reads `if [ -f .sealed/test-hashes.json ]` — **on the Builder worktree this condition is false and Check 2 silently no-ops** (`pre-commit:5` `set -e` is harmless because the branch is skipped). The append-only rule is enforced where the rule is least at risk (Critic worktree) and unenforced where the threat lives (Builder worktree). Falsifier: have Builder modify an existing test file and commit. CHARTER_WATCHLIST.md:55 admits exactly this: "the hook lives in the Builder's worktree (which doesn't have `.sealed/`); the Critic's `security-reviewer` is the authoritative gate." So the prediction reduces to "Critic will catch it" — which is a *social* falsifier, not a *mechanical* one.

3. **Sealed eval is physically unreadable to Builder.** `README.md:21-22`, `CHARTER.md:17`. Falsifier: instrument the Builder session and observe any read syscall on `.sealed/`. The plan offers `gitignore` + worktree separation as the mechanism — **there is no alarm trip**, no audit log of Builder filesystem reads, no canary file. Detection is "hope." Falsification path exists in principle (incident-003-style spec/eval mismatch is the *symptom* a Builder read would mask), but the plan provides no positive surveillance.

4. **Two same-seed runs produce byte-identical snapshot/frames** (`README.md:94, 115-116`). Cleanly falsifiable; `tests/test_world_determinism.py`, `tests/test_weight_buffer_determinism.py` describe the observation. This is the strongest prediction in the corpus.

5. **`eval_03_brain_learns.py` shows trained brains outperform random-walk by a "statistically significant margin"** (`ROADMAP.md:104`, `MILESTONES.md:124-127`). Falsifier: run the eval; observe paired-seed mean reward difference below threshold. **The threshold is unspecified in the visible governance** ("a configured margin" — MILESTONES.md:126) and lives only inside `.sealed/`. This is falsifiable in principle, slippery in practice: the threshold is mutable by Critic, which is also the role that decides whether the threshold was met.

6. **`[critic-approved]` commits are gated by an independent triad of subagents** (`PM_RUNBOOK.md:319-323`, `incident-002` cycle 14). Falsifier: a commit lands as `[critic-approved]` without corresponding `.loop/critic-verdicts/T-NNN.verdict.json`. **Already partially refuted** in evidence: `critic-overrule-001-T-016.md:96-103` records that the queue transition was "bundled into PM's `d39cbd4` commit" because of the shared git index — the verdict reasoning was NOT in the `[critic-approved]` audit trail; the retro file is the only public record. The mechanism is leaky.

7. **Stuck-state triggers fire on real stalls** (`orchestrator.py:178-326`). Falsifier: a 60-minute multi-role stall passes without triggers writing `.loop/stuck-state.json`. **Already refuted by req-013** (`governance/requests/2026-05-12-013...md:1-91`): PM + Builder heartbeats ~63 minutes stale across three Critic sessions, orchestrator fresh, *no `stuck-state.json` referenced* — the watchdog couldn't see it because PM/Builder write heartbeat mtime without advancing content fields, and the relevant trigger only fires on content non-advance under mtime advance, which their idle loops did not produce. The PM disposition admits this: "Case (b) CONFIRMED." Detection design is defective.

8. **PM hard-pivots after 2 failed recoveries** (`CHARTER.md:38`, `PM_RUNBOOK.md:391-398`). Falsifier: 2 recovery proposals VETOed by Critic in the same sprint without a `[pm-pivot]` commit on the third event. **Highly elastic.** "Failed recovery" is nowhere defined — is a Critic VETO a fail? A partial scope-cut that doesn't actually unblock? Architect re-runs (PM_RUNBOOK.md:390) appear to *reset the counter* implicitly. The rule is unfalsifiable as written.

---

## Unfalsifiable claims dressed as predictions

1. **"Mutation testing. Critic periodically injects bugs into the codebase and verifies the test suite catches them; weak tests trigger a hardening sprint"** (`README.md:26`). `Grep` for `mutmut`/`cosmic-ray`/`mutation`-as-tooling across `tests/` returns *one* unrelated file. There is no mutation-testing harness in the repo, no schedule, no operational definition of "periodically," no archived hardening sprint. The claim cannot fail because it has no behavior to observe.

2. **"`[pm-emergency]` is restoring the gate, not bypassing"** (`EMERGENCY_PROTOCOL.md:30-44`). The distinction is intent-coded, not behavior-coded. Any action PM takes can be re-narrated as "restoring." The retro/Critic-retrospective review (`EMERGENCY_PROTOCOL.md:88-103`) explicitly says disagreements are "recorded forward, NOT a revert" — so a `[pm-emergency]` that was *actually* a gate bypass cannot be undone, only annotated.

3. **"On 2 failed recoveries: PM hard-pivots"** (`CHARTER.md:38`). Discussed above. Counter, definition, and adjudicator are all PM-internal.

4. **"The triad cannot be replaced or merged"** (`CHARTER.md:24`). The cycle-55-to-57 evidence shows PM and Builder went heartbeat-silent for >60 min across three sessions (`requests/2026-05-12-013...md:39-46`) while Critic was the only role committing. That is functional triad collapse, but the rule survives because nothing was *named* a merge.

5. **Sprint exit criteria include `python -m pytest tests/ -q` is green** (`SPRINTS/current.md:53`). Green pytest is falsifiable, but the *sprint goal* "spectator can observe agents accumulating non-zero energy" (`SPRINTS/current.md:46-49`) has no operational pass/fail bound — what counts as non-zero, over what window, on what seed grid?

---

## Ad-hoc rescue risks

1. **The recovery counter (`CHARTER.md:38`).** When recovery #2 "fails," PM will reinterpret it as a partial success, change the diagnosis, dispatch a fresh `architect`, and reset the counter. There is no commit prefix that *records* "recovery N marked failed" — the counter is implicit.

2. **Critic single-pass verdicts under load** (`incident-002` close, cycle 14: "Critic adapted under pressure — used single-pass verdicts instead of full triad for recovery-velocity, explicitly noted in the verdict JSON's `approved_by` field"). This is exactly the ad-hoc rescue Charter §3 warns against, and PM endorsed it. The "PM endorses" sentence is the rescue. There is no quantified ceiling on how long single-pass mode persists; the bound is "Critic's own throttle."

3. **`CRITIC_EXCEPTIONS.md` (`governance/CRITIC_EXCEPTIONS.md:31-32`).** Watchlist VETOes can be PM-pre-empted with a single signed entry. Currently empty, but the mechanism is a built-in escape hatch: when a Builder cycle needs to mutate `_netguard.py`, PM writes the exception, mutation lands. Falsifier on the network-isolation claim collapses into "PM thought it was safe."

4. **Heartbeat-silence redefined as non-defect** (`requests/2026-05-12-013...md:158-178`). PM disposition: "the loop was operating as designed." Three-session multi-role stall reframed as a discipline gap with a proposed-but-deferred D-010. The behavior changes; the predictions don't.

5. **Critic overruling its own subagents** (`critic-overrule-001-T-016.md:67-72`). Critic protocol authority allows the Critic to overrule a VETO with "Critic re-verifies." Falsification of a Builder commit via subagent VETO is convertible to APPROVE by the same role that authored both. The triad's independence is one decision deep.

---

## The single experiment most likely to refute the plan

**Run mutation testing on the Critic.** Specifically: inject a known-bad change into `norns/world.py` (e.g. `world.time` advances by 2 instead of 1, or `World.snapshot()` returns a stable hash regardless of state) on a Builder-style branch, route it through the queue as a normal Builder commit, and observe whether *Critic's sealed eval + dispatched triad* catches it without the bug being telegraphed in the commit message.

Why this one: every other guarantee in the design — append-only tests, sealed evals, network isolation, charter hash — is downstream of one assumption: **the Critic detects substantive defects independently.** If the Critic rubber-stamps a planted regression, then `[critic-approved]` is decorative, sealed evals don't actually constrain the Builder (incident-003 already showed PM can author a spec that the eval rejects; the inverse — Critic missing a defect the eval should catch — has not been tested), and the entire "three Claude sessions autonomously build ALife" prediction reduces to "they produce commits that pass each other's review," which is consistent with any output. The README at line 26 *claims* this experiment runs periodically; the repo shows no evidence it has ever run.

Refutation of this single experiment would force the team to admit the gate is unreliable. Confirmation would let the rest of the design stand.

---

## Where the milestone-fail evidence lives — and doesn't

The plan has no terminal failure criterion. The hard-pivot rule (`CHARTER.md:38`) escapes upward to "next milestone" — but M6 is the last named milestone, and `ROADMAP.md` does not specify what happens if M6 hard-pivots. The loop's design is structurally incapable of admitting "the loop doesn't work" because every failure routes to a recovery, a retro, a `[pm-pivot]`, or a deferred D-NNN. The closest thing to a terminal falsifier is `CHARTER_VIOLATION.md` (`orchestrator.py:95-103`), which halts the orchestrator — but that only triggers on charter byte-drift, not on "the sim never produces a brain that learns."

A Popperian addition: define a wall-clock or cycle-count budget per milestone in `MILESTONES.md`. If `eval_0N` has not gone green after K cycles, the loop is declared falsified for that milestone, archived, and the experiment ends — not pivoted, *ended*. Until such a bound exists, "three Claudes can build ALife" is unfalsifiable: there is always another sprint.

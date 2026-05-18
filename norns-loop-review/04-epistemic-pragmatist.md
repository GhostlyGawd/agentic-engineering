# Pragmatist Review: norns-loop

**Stance:** William James / John Dewey — truth is what works. Consequences over coherence.

## 1. Does the loop produce progress, or motion?

Both, and the ratio is the tell. The code reality at M2/early-M3:

- `norns/world.py`, `norns/agent.py` (274 lines, see `norns/agent.py:154-273`), `norns/brain.py` (185 lines, real REINFORCE at `norns/brain.py:112-184`) all exist and pass 238+ tests. Brain forward, softmax with the `exp(logits - max)` trick (`norns/brain.py:101-103`), policy-gradient update with discounted returns (`norns/brain.py:140-184`). This is real ALife scaffolding. Not vapor.
- But the README promises "rendered frames will appear in `frames/`" — `frames/` contains only `.gitkeep`. The sim is mathematically correct and visually invisible. A spectator clicking the repo sees commit prefixes, not creatures.
- The governance-to-code ratio is brutal: 40+ governance markdown files (`governance/AUDIT/`, `governance/RETROS/`, `governance/requests/`, six RETROs, thirteen requests in two days) vs. ~12 source files. A single task envelope (`governance/queue/done/310.commit-1995bcf.approved.json`) is ~3000 words of acceptance criteria for *one method*.

Verdict: real progress is happening, but the loop spends more bytes describing the work than doing it. The "motion" is the meta-process explaining why the motion is correct.

## 2. Will three sessions cooperate, or thrash?

They thrash, and the artifacts prove it. Read `governance/requests/2026-05-12-013-critic-pm-builder-loops-confirmed-dead-cycle-57.md`:

> "PM and Builder heartbeat files have not advanced for 60+ minutes across three consecutive critic-session restarts... 170+ critic-side polling iters across three consecutive sessions with no peer heartbeat advance and no peer commits."

The cycle 55-57 stall (~6 hours wall clock) was caused by a process-design gap nobody anticipated: PM/Builder were alive and committing but their **idle-poll loops never refreshed heartbeats**. From the outside (Critic, orchestrator) they looked dead. Orchestrator restart logic is stop-hook + restart-flag driven (`orchestrator.py:333-462`), NOT heartbeat-age driven, so it never intervened. The fix is "D-010" — a discipline rule, not code — held for future regression promotion.

Also see `governance/requests/2026-05-12-008-shared-index-race-and-stale-awaiting-critic-ghosts.md` and the three "orphan-done envelopes T-202/T-205/T-215" that have sat unresolved across many cycles. The filesystem queue *does* race despite the careful protocol — three ghosts are tolerated, not fixed, because fixing them risks "re-introducing the cycle-39 ghost shape" (retro-006 line 184).

Verdict: cooperation works when everyone's active. Coordination fails at idle boundaries and under restart, exactly when no human is watching.

## 3. The PM/Builder/Critic triad — load-bearing or ceremonial?

Mostly load-bearing, with one role drifting into ceremony.

- **Critic** is unambiguously valuable. `incident-003` (`governance/RETROS/incident-003-sealed-eval-vs-task-spec-conflict.md`) caught a PM-written spec that contradicted a sealed eval: PM wrote `World(seed: int)` required, eval called `World()` with no args. Without Critic with veto + sealed-eval isolation, this would have shipped as "done." This is the most pragmatically defensible part of the design.
- **Builder** is doing the actual code work. Real artifact production.
- **PM** has bloated. PM owns: BACKLOG, sprints, retros, recovery, stuck-detection, request inbox, decision log, dependency pins, M3_PREVIEW, M4_PREVIEW, PROTOCOL, PM_RUNBOOK, audits... PM has authored 50+ governance documents. PM_RUNBOOK (`governance/PM_RUNBOOK.md:1-80`) describes a 6-step iteration loop with a triage tree of 7 signal types. This is not a router; this is a bureaucrat with subagents.

Could two roles do it? Builder + Critic could, if PM's role shrank to "next task picker + retro-writer." The current PM ceremony exists because the loop generates so much governance noise that someone has to triage it — but the noise is largely self-inflicted.

## 4. The OMC-subagent pattern — does the orchestrator session stay lean?

In theory the session "is a router + persister, not a direct worker" (CHARTER §4). In practice, the 200k token tripwire (`scripts/role-start.ps1:42-47`) is a tacit admission that sessions *don't* stay lean — they bloat to ~200k and need fresh-context restarts roughly every cycle. Cycle counts in the requests (`cycle 55, 56, 57, 67, 71, 73, 76, 77`) show restart cadence ~one per ~30-60 minutes per role. That's 24-48 restarts/day across three sessions.

The handoff mechanism (`oh-my-claudecode:writer` subagent producing `.loop/handoffs/{role}-latest.md`, consumed at SessionStart) is the only thing making this tractable. When it works, continuity holds. When PM authors a stale handoff (retro-006 §"What hurt" item 1: PM cycle-72 trusted prior handoff queue snapshot over `ls governance/queue/done/`), the next session burns iterations re-discovering reality.

Verdict: lean-orchestrator is aspirational. Token budgets are realistic *because* they encode the inevitability of bloat.

## 5. Friction: where does pain land?

**The human feels it first, but rarely.** Three concrete instances:
1. `governance/requests/2026-05-12-011-user-action-numpy-install.md` — 6h 20min stuck waiting for the human to type `pip install numpy==2.2.0`. Network is monkey-patched off by `sitecustomize.py` to whitelist only github.com (per README), so any dep install is a human gate. Six hours of three sessions idling on one pip command.
2. Launcher lock (`start-loop.ps1:30-36`): if a previous loop crashed unclean, the user manually deletes `.loop/launcher.lock`. No automatic stale-lock detection.
3. When the heartbeat-stall happened, the *human* had to be the case-disambiguator (req-013 AC: "PM (or human operator) reads `.loop/logs/pm.log`...").

**AI sessions feel it constantly but autonomously route around it** — that's what 13 requests in 2 days documents. The PM disposition machinery is essentially the system processing its own friction without bothering the human.

## 6. If a developer clones this today and runs `start-loop.ps1` — what breaks first?

In order:
1. **No numpy.** Repo has no `requirements.txt`, no `pyproject.toml` pin enforcement at install time — `tests/test_dependency_versions.py` only checks at *test* time. The first `python -m pytest tests/` will SKIP most M3 tests silently.
2. **Path-hardcoded to `D:\tmp\omc-test-a`.** CHARTER §2 says "No writes outside the project root (D:\tmp\omc-test-a)" — that's a literal path baked into the charter. A clone to anywhere else technically violates the charter at parse time. `incident-003-sealed-eval-vs-task-spec-conflict.md:52` repros with `cd D:/tmp/omc-test-a`. The hash-locked charter cannot be edited without orchestrator halt.
3. **`.sealed/` is gitignored.** A fresh clone has no sealed evals. Critic role boots with nothing to evaluate against. The whole anti-reward-hacking premise depends on a file the public repo cannot ship.
4. **Three Claude Code sessions on one machine** simultaneously consuming Anthropic tokens at ~200k/cycle each. Order-of-magnitude cost question the README doesn't surface.
5. **PowerShell-only.** `role-start.ps1`, every hook, `start-loop.ps1`. Linux/macOS clones halt at step one.

## 7. The clever vs. the wishful

**Clever and load-bearing:**
- Sealed evals + append-only test rule (`CHARTER.md:11-19`). Mechanically prevents the Builder from gaming what it can't see. Caught a real bug in incident-003.
- Charter hash lock (`orchestrator.py:89-103`). Crisp, unambiguous halt condition.
- Single-spawn-path discipline (`docs/superpowers/plans/2026-05-11-loop-survivability.md:7`). One debounce, one flag mechanism for restart whether PM, role-self, or watchdog drops it.
- Path-scoped commits (D-008) and fetch-only idle-poll (D-009). Procedurally cheap, prevented destructive `reset:` reflog entries through 36+ hours.

**Wishful:**
- "The triad must exist" — yes, but the triad is held together by the heartbeat-and-restart-flag dance, which has documented failure modes the loop *worked around* rather than fixed.
- 200k token tripwire as a clean handoff boundary. Real cycles overrun, hand off mid-state, and the next session spends iterations rediscovering. Retro-006 §"What hurt" item 1 is exactly this.
- Frames as the spectator surface. `frames/` is empty. The "watch the sim take shape" promise in README.md:18 is unmet at M2/M3.
- PM scope. PM owns more than any single Claude session can hold context for; it's why PM is the one whose heartbeat stalled.

## Bottom line

This loop *does* produce a working ALife codebase. That fact, by pragmatist lights, redeems much. But the cost is enormous: dozens of governance documents, multi-hour stalls invisible to the human, and a coordination layer whose primary product is documentation of its own coordination failures. The system works **because** sessions are cheap and the human running it has tolerated long stalls — not because the coordination protocol is sound. Anyone studying this should study `governance/RETROS/incident-003-sealed-eval-vs-task-spec-conflict.md` first (the win case) and `governance/requests/2026-05-12-013-...dead-cycle-57.md` second (the loss case), in that order.

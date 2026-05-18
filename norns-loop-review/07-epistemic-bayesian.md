# Bayesian Review — norns-loop

## Project-level prior

Reference class: autonomous multi-session AI coding loops chartered toward open-ended ALife goals (NN brains, biochemistry, DNA, breeding) with no human in the inner loop. There is no published base rate because the reference class barely has N>5. Adjacent reference class — autonomous agent loops aiming at non-trivial software targets — empirically stall in governance/looping/reward-hacking long before reaching the open-ended creative goal. My prior on **full charter goal (M1-M6 with real NN learning, biochem, DNA, breeding) being completed by the loop autonomously**: roughly **P ≈ 0.05**. My prior on **the loop reaching a useful intermediate state (M3 with demonstrable learning) before the human runner stops it**: roughly **P ≈ 0.35**. M1 and M2 are already closed per `governance/MILESTONES.md:12` and `:73`, so the right unit of analysis is the *remaining* chain.

## Per-component probability table

| Component | P(works as designed) | Why |
|---|---|---|
| Charter hash-lock trips on drift | 0.9 | `orchestrator.py:89-103` reads `.charter-lock`, recomputes sha256, exits and writes `CHARTER_VIOLATION.md`. Simple, well-isolated. Failure mode: orchestrator not running — but `start-loop.ps1` and stop hooks address this. |
| Network guard catches egress | 0.7 | `_netguard.py:5-41` patches `socket.getaddrinfo` and `socket.create_connection`. Incident-001 already showed `sitecustomize.py` did NOT auto-load; remediated by explicit `conftest.py` import (`conftest.py:1`). But: a subagent that shells out via `subprocess` to anything but git/gh, uses `gh api` to exfiltrate, or imports a C extension that bypasses `_socket` — all bypassable. The settings.json deny list (`.claude/settings.json:7-19`) is a defense-in-depth, not a sandbox. |
| Sealed eval isolation holds | 0.6 | `.sealed/` is gitignored per `README.md:23`, but it sits in the same filesystem the Builder's OMC subagents traverse. The Builder's session prompt says "never read `.sealed/`" — this is a *policy*, not a kernel boundary. Probability the Builder reads it accidentally (e.g. via a recursive grep, a code-editor subagent doing a workspace search) is non-trivial. Per-role worktrees are listed as **STILL DEFERRED** in `retro-006.md:280-283`. |
| Tests/evals append-only | 0.7 | Charter constraint (`CHARTER.md:14-16`) is policy; enforcement is hash-tracking via pre-commit (`README.md:22`). The hook lives in repo; a subagent with Edit access to `.git/hooks` could weaken it — though `guard-meta-writes.ps1:52-58` does block `.claude/hooks/**` writes. Hash-check pre-commit not visibly enforced for `tests/` — needs verification. |
| PM correctly diagnoses stuck-state | 0.5 | `orchestrator.py:178-326` writes triggers (sprint_age, veto_streak, stuck_iteration, verdict_latency, zombie_heartbeat) for the PM to consume. Triggers are detectable; *response quality* is where the prior drops — PM is an LLM session reading a JSON file and writing a recovery proposal. Incident-001-pm-response and incident-003-pm-response exist and were correct; n=2 from the historical record. |
| Critic doesn't drift to rubber-stamping | 0.4 | `retro-006.md:36-46` notes **18 consecutive approvals without a single VETO**. Two interpretations: (a) pre-claim audit is working; (b) Critic has drifted to rubber-stamping. The retro itself names the concern. With no recent VETO signal, you cannot distinguish. This is the classic alignment-flavored failure for AI-on-AI review. |
| Three sessions cooperate via FS queue | 0.7 | Demonstrated through M2 close (`README.md:73-80`). But req-009 (Builder's `git reset --hard origin/main` every 8s wiping peer working trees, `retro-005.md:42-67`) is exactly the failure mode of "shared worktree, polling, no coordinator" — and the disposition is **procedural-only defense, no PreToolUse guard**. Will recur with a different shell pattern. |
| Token-budget handoff preserves continuity | 0.6 | Charter §7 specifies 200k/250k thresholds with `oh-my-claudecode:writer` handoffs. Handoffs are LLM-summary documents — lossy by definition. `retro-006.md:124-141` documents "Heartbeat staleness gap" where PM's handoff cache was treated as queue ground truth and missed a verdict — exactly the silent-context-drop failure pattern. |
| Stuck-state recovery actions execute correctly | 0.5 | `CHARTER.md:36-37` allows revert / scope-cut / refactor / hard-pivot. After 2 failed recoveries, hard-pivot to next milestone. The hard-pivot is the failsafe — but pivoting *past* M3 without real learning means M4-M6 build on a non-functional substrate. The "2 failed recoveries" rule pushes the loop forward even when standing still would be wiser. |
| M3 (real RL learning) closes correctly | 0.4 | `retro-006.md:30-34` shows real progress: numpy pinned, RNG shim, weight buffer determinism, Brain class with forward + softmax act. But the actual sealed eval (`eval_03_brain_learns.py`) requires a *trained cohort statistically beating random* under paired seeds (`MILESTONES.md:121-127`) — this is the first milestone where the loop must produce *learning*, not just plumbing. Toy-task design quality, REINFORCE variance, and seed-count for stable eval are all open. |
| M4 biochemistry closes correctly | 0.3 | `MILESTONES.md:184-186` already flags "Numerical drift over long runs may break byte-identical trajectory determinism if floats are used. May require fixed-point or rationals." This is the load-bearing tension between *reproducibility* (the loop's safety net) and *biology* (the goal). |
| M5 DNA expression closes correctly | 0.2 | Same float-determinism tension at higher dimension (`MILESTONES.md:215-217`). Requires correct, novel design of an expression function (bytes → brain spec + biochem spec) by the loop itself, gated by a sealed eval the Builder cannot see. |
| M6 breeding/inheritance closes correctly | 0.2 | `MILESTONES.md:246-249` flags selection-pressure design as load-bearing. Population-genetics calibration is a research problem, not an engineering task. |
| Human runner's tolerance outlasts runtime | 0.3 | The loop has 3 windows tying up a machine. The retros are 300+ lines per cycle. Even at sprint-002's "7 closures/day" (`retro-006.md:256`) and 16 tasks per milestone, M3 → M6 is ~4 × 16 = 64 tasks ≈ 9 days of wall-clock with no incidents. Real incident rate is non-zero. Realistically: weeks of attended runtime. |

## Dependency chains where joint probability is the real story

**Chain A — Reaching M3 close with genuine learning:** PM diagnosis (0.5) × Critic-non-rubber-stamp (0.4) × queue cooperation (0.7) × handoff continuity (0.6) × M3 eval-design quality (0.4) ≈ **0.03**. The Critic-drift and PM-diagnosis links dominate.

**Chain B — Sealed-eval contract integrity through M3:** sealed-eval isolation (0.6) × append-only enforcement (0.7) × no PM/Builder eval-contract drift (0.6, given incident-003 already happened once at M1) ≈ **0.25**. Incident-003 (`governance/RETROS/incident-003-sealed-eval-vs-task-spec-conflict.md`) is a recurring class of failure: the sealed eval IS the contract and the PM cannot see it, so PM-written task specs can violate it. Will recur at M3-M6.

**Chain C — Reaching M6 charter goal:** P(M3) × P(M4|M3) × P(M5|M4) × P(M6|M5) × P(human runs it long enough) ≈ 0.4 × 0.5 × 0.5 × 0.4 × 0.3 ≈ **0.012**. Note these P-conditionals are higher than the marginals because conditioning on prior-milestone-close screens out the worst failure modes. The 0.3 human-tolerance multiplier is the biggest single drag.

**Chain D — Sandbox holds through full run:** network guard (0.7) × no Builder-subagent reads `.sealed/` (0.6) × no destructive worktree race recurs (0.5, given req-009 has a procedural-only fix) ≈ **0.21**.

## Correlated failures (not simple products)

- **Shared-worktree model is a single failure surface.** If the FS-queue model breaks once (req-009 already showed this), it takes out queue cooperation, sealed-eval isolation (worktree-shared), and handoff continuity together. These three are NOT independent; their true joint failure prob is closer to max(p_fail) than to product.
- **Critic drift and PM-misdiagnosis correlate.** Both are "LLM evaluating LLM output over long context with no fresh ground truth." A model update, a context-window degradation, or systematic miscalibration hits both at once. Treat their joint as ~ max(0.4, 0.5) = 0.5 P(at least one fails), not 0.2.
- **Determinism-vs-biology tension hits M4 + M5 + M6 simultaneously.** If float determinism doesn't hold, all three sealed evals fail in the same way. One design decision, three milestone outcomes.

## Lowest-probability links that dominate the tail

1. **Human runner's tolerance (~0.3).** The single biggest swing factor — and the easiest to update against.
2. **Critic drift to rubber-stamping (~0.4).** 18 clean approvals without a VETO is the signal you cannot interpret; needs an injected-defect mutation test to disambiguate (this is gestured at in `README.md:25` as "Critic periodically injects bugs" — verify it actually runs).
3. **M3 learning-eval design quality (~0.4).** First milestone where the loop must produce a research artifact, not plumbing. The transition from "build the substrate" to "do the science" is where most autonomous-research projects break.

## What would most update these priors

- **Inject a defect and see if Critic catches it** — the mutation-testing claim in `README.md:25`. If yes, Critic-drift prior moves up to 0.7+. Cheapest single experiment.
- **Try to read `.sealed/` from the Builder session.** If the policy holds only by prompt and not by worktree separation, sealed-eval isolation drops to 0.3.
- **Audit the last 18 approvals for any non-trivial code change.** If they are all plumbing/refactors/docs, the no-VETO streak means little. If they include real algorithmic decisions, it means more.

**Posterior on the full charter goal being achieved by the loop autonomously: ~0.01-0.05. Posterior on the loop producing demonstrable learning (M3 close with genuine eval pass): ~0.2-0.4. Posterior on the loop being an instructive failure that produces a publishable architecture even if it doesn't ship M6: ~0.7.**

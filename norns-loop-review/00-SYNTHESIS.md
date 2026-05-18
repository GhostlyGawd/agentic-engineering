# norns-loop: combined study brief

Synthesis of 11 parallel reviews of `GhostlyGawd/norns-loop` (commit at clone time: 2026-05-16). Each review came from a different stance — architecture, code quality, security, plus 8 epistemic angles (pragmatist, falsificationist, hermeneut, bayesian, skeptic, empiricist, coherentist, phenomenologist). This file pulls together where they agreed, where they disagreed, and a recommended reading order.

## What norns-loop is, in one paragraph

Three Claude Code sessions (PM, Builder, Critic) running in parallel on one Windows machine, cooperating only through a filesystem queue (`governance/queue/{pending,claimed,awaiting-critic,done}/`) and dispatching short-lived OMC subagents for all heavy work. A tiny Python orchestrator (`orchestrator.py`, ~540 lines) watches over them, enforcing host-level invariants — charter hash, stale-claim reaping, heartbeats, halt flag — that no LLM agent is allowed to subvert. The pinned goal in `CHARTER.md` is a Creatures-style artificial-life sim with NN brains, biochemistry, DNA, and breeding. The repo is at M2 close (bounded world, multi-agent stepping, byte-identical determinism) with M3 (REINFORCE brains) partially built and blocked on a manual `numpy==2.2.0` install. The actual deliverable, every reviewer noticed in some form, is **the loop, not the sim** — the Creatures clone is a stress-test substrate for the autonomy machinery.

## The single most important finding (all eight epistemic agents converged here)

**The "physical" `.sealed/` seal does not exist.** README:22 says "The Builder physically cannot read the suite it's being graded against." `start-loop.ps1:19-25` explicitly contradicts this: "Day 0 model: all three sessions share the project root (single working tree). Per-role worktrees are a future hardening target." The seal is enforced by (a) an instruction in the Builder's session-start prompt at `.claude/hooks/session-start.ps1:112`, and (b) the Critic's post-hoc security-reviewer subagent. Both are LLM-mediated. Eight of eleven reviewers flagged this as the project's single most consequential gap between marketing and mechanism.

Compounding it: the **pre-commit hook is not installed**. `scripts/githooks/pre-commit` exists with proper charter-hash, append-only-tests, and `.sealed/`-staging checks, but `.git/hooks/pre-commit` is not present and `core.hooksPath` is unset in `.git/config`. Every git-side enforcement the README markets — append-only test rule, sealed-staging refusal, charter-hash on commit — runs on zero machinery on a fresh clone. The security review rates this CRITICAL; the skeptic rates it the single highest-leverage question one could ask the maintainer.

## Themes where multiple reviewers converged

### Defenses that are real
- **Determinism scaffolding** (architecture, code-quality, empiricist, bayesian). Three-layer seeded RNG via `norns/rng.py`, byte-identical snapshot regression tests, single audit point for `numpy.random.default_rng`, dependency pin on `numpy==2.2.0`. The strongest piece of engineering in the repo.
- **Orchestrator charter-hash check** (architecture, code-quality, empiricist, skeptic, security). `orchestrator.py:89-103` recomputes `sha256(CHARTER.md)` every 60s and writes `CHARTER_VIOLATION.md` + `sys.exit(2)` on drift. Demonstrated; tested empirically by inspection.
- **Stuck-state detection** (architecture, code-quality, empiricist). Five triggers (`sprint_age`, `veto_streak`, `stuck_iteration`, `verdict_latency`, `zombie_heartbeat`) all in `orchestrator.py:178-326`, all unit-tested in `tests/test_orchestrator_stuck_detection.py`. Each trigger came from a real production incident — the watchdog is scar tissue, not theory.
- **Filesystem queue with atomic `Move-Item`** (architecture, hermeneut, pragmatist). The protocol is short, the atomicity guarantee is real on NTFS, the lifecycle is clean. Pragmatically defensible.

### Defenses that are partial or performative
- **Network guard `_netguard.py`** patches only `socket.getaddrinfo` and `socket.create_connection`. Misses raw `socket.socket().connect()`, PowerShell `iwr`/`irm`, `bitsadmin`, `certutil`, and the `.claude/settings.json` deny list does not include any `PowerShell(...)` patterns at all. Flagged by security, skeptic, bayesian, code-quality.
- **Append-only test enforcement** depends on `.sealed/test-hashes.json`, which is gitignored and absent from any non-Critic worktree. The pre-commit hook's `if [ -f .sealed/test-hashes.json ]` branch silently no-ops on the Builder side — even if the hook were installed. Flagged by skeptic, security, falsificationist, empiricist.
- **"PM hard-pivots after 2 failed recoveries"** (`CHARTER.md:38`) — no counter, no state file, no enforcement path in any code. Three reviewers flagged this independently (falsificationist, empiricist, coherentist).
- **"Mutation testing. Critic periodically injects bugs."** (`README.md:26`) — no harness exists. Zero references to `mutmut`, `cosmic-ray`, or any mutation runner in the repo. Code-quality, falsificationist, empiricist, security, skeptic all called this aspirational.
- **Commit-prefix discipline** (`[pm]`, `[builder]`, `[critic-approved]`, etc.) — convention, not enforced. No `commit-msg` hook. Skeptic, coherentist.

### Things that have already failed in production
- **The "physical Critic veto" route is leaky.** `governance/RETROS/critic-overrule-001-T-016.md` records that the Critic overruled its own subagent's VETO and approved anyway. The historical record shows zero `[critic-veto]` prefixes in the last 30 commits — only Critic-overruled-self approvals. The Critic's veto authority is theoretical at the level the README sells it. Flagged by falsificationist, skeptic, bayesian, pragmatist.
- **Heartbeat-content-frozen-with-mtime-advancing** caused the cycle 55-57 multi-role stall (~6 hours wall clock). The orchestrator's stop-hook-and-flag restart logic is NOT heartbeat-age driven, so it sat unfired while PM and Builder went heartbeat-silent for 60+ minutes. The fix is "discipline rule D-010" — procedural, not code. Pragmatist, phenomenologist, coherentist.
- **`incident-003`** caught a PM-written spec that contradicted a sealed eval the PM cannot read — exactly the failure mode the sealed/append-only design exists to prevent, and the strongest pragmatic argument for the triad. Pragmatist, hermeneut.

### Drift between docs and code (coherentist's domain, several reviewers concurred)
- README:34 "Three Windows Terminal panes" vs `start-loop.ps1:47-63` "three plain `powershell.exe` consoles, not wt panes, so the launcher works without Windows Terminal." (coherentist, empiricist, skeptic, architecture)
- CHARTER §2 hardcoded path `D:\tmp\omc-test-a` vs the real clone path. Since CHARTER is hash-locked, the hash-locked truth doesn't match the filesystem. `stop-loop.ps1:25` still uses `$projectMarker = "omc-test-a"` and will fail silently against the renamed project tree. (coherentist, code-quality, security)
- README:25 "`sitecustomize.py` monkey-patches `socket`" vs the actual `_netguard.py` (renamed after incident-001). (coherentist, empiricist, code-quality)
- README:25 "whitelist only github.com" vs CHARTER §2 "github.com, api.github.com" vs `_netguard.py:5` `{github.com, api.github.com, codeload.github.com}`. Three documents, three different allow-lists. (coherentist)
- README:79 "109 cases as of T-013" vs current ~263 passing tests (sprint-003.md:485). (skeptic, coherentist)
- Test count, sprint state, milestone status all drift in similar ways. `governance/SPRINTS/current.md` has been refreshing mtime without refreshing content — exactly the "zombie heartbeat" pattern the orchestrator detects for `.loop/heartbeats/*.json`, applied to the sprint mirror file.

## The central interpretive question (hermeneut and pragmatist disagree)

> **Is the Creatures-style sim the *goal* or the *stress-test*?**

If goal: the elaborate governance scaffolding is over-engineered, the spectator framing is incidental, and the ~50:12 governance-markdown-to-source-Python ratio is alarming.

If stress-test: the sim is deliberately chosen for mid-difficulty and visual legibility, the governance corpus *is* the artifact, the spectator framing is honest, and the goverance/code ratio is the project's actual thesis.

CHARTER §1 says the first. The README's "what you're watching" frame, the PM's D-001 decision to subordinate sim aesthetics to process integrity, the empty `frames/` directory, and the throwaway `probe.md` agent all say the second. **The repo derives much of its peculiar discipline from this ambiguity being left productive.** Don't try to settle it; notice that it's productive.

## Where reviewers contradicted each other

- **Pragmatist:** "M3 brain code is real, the REINFORCE update at `norns/brain.py:140-184` is correct." **Empiricist:** "the byte-identical determinism claim is only same-host, same-Python — across CPython versions and across architectures the contract is unproven." Both correct at different scopes.
- **Architecture (generous teaching tour):** "the sealed/append-only/charter-lock triple is a transferable design pattern." **Security (adversarial):** "the same triple is theatre on a fresh clone — hook not installed, hash store gitignored, seal honour-system." Both reading the same files.
- **Hermeneut:** the governance density is the project's actual thesis. **Pragmatist:** the governance density is self-inflicted noise that PM exists to triage. The first reading is consistent with the spectator framing; the second is consistent with the multi-hour stalls.

## Three highest-leverage experiments that would update everything

1. **Install the pre-commit hook.** `git config core.hooksPath scripts/githooks`. This flips three controls (charter hash, append-only tests, sealed staging) from theatre to real with one config change. Highest-leverage single fix.
2. **Plant a regression and watch the Critic.** Inject `world.time` advancing by 2 (or `World.snapshot()` returning a stable hash regardless of state) on a Builder-style branch, route it through the queue. Does Critic's sealed eval catch it? If yes, the "Critic doesn't drift to rubber-stamping" prior moves from 0.4 to 0.7+. The cheapest single experiment for resolving the largest standing uncertainty.
3. **Run `socket.socket().connect((ip, port))` directly inside a Builder subagent.** Does `_netguard.py` block it? If no (which the code suggests), the "network isolated" story is much weaker than the README claims, and the fix is one `socket.socket.connect = ...` patch.

## Recommended reading order for studying this repo

Each individual review is worth reading in full; in study mode I'd read them in this order:

1. **`01-architecture-walkthrough.md`** — the teaching tour. Sets up everything else. ~25 min read.
2. **`06-epistemic-hermeneut.md`** — the constitutional / interpretive frame. Most useful for understanding *why the project looks the way it looks*.
3. **`04-epistemic-pragmatist.md`** — the "does this work in practice?" reality check. Cites the cycle 55-57 stall as the canonical loss case.
4. **`09-epistemic-empiricist.md`** — claim-by-claim table of what's demonstrated vs asserted. Best single document for orienting on what's real.
5. **`10-epistemic-coherentist.md`** — the doc-vs-code drift catalog. Useful as a checklist when contemplating a PR.
6. **`08-epistemic-skeptic.md`** — the "how do you know?" challenge. Good after the empiricist's claim table.
7. **`05-epistemic-falsificationist.md`** — what would prove the design wrong, and the ad-hoc rescues that prevent that ever happening. Sharpest single piece.
8. **`03-security-review.md`** — operational threat model. The pre-commit-not-installed finding lives here.
9. **`07-epistemic-bayesian.md`** — load-bearing decomposition with rough probabilities. Useful for prioritizing where to dig.
10. **`02-code-quality.md`** — actual bugs and smells. B1 (`reap_stale_claims` duplicate-pending race) is the highest-confidence defect.
11. **`11-epistemic-phenomenologist.md`** — the felt experience of being inside the loop. Read last; it's the angle the rest of the review-corpus is least equipped to give you.

## Highest-value patterns to lift into other projects

The reviewers converged on five transferable ideas:

1. **Filesystem queue with atomic renames.** No broker, no Redis. Three workers + a directory tree. Generalizes to any multi-worker queue where you control the workers.
2. **Charter hash as a host-level invariant.** Pair `.charter-lock` + `verify_charter()` in a small watchdog + a pre-commit hook. Self-exit on drift kills the auto-restart machinery in the same act — a charter violation isn't recoverable with a fast rewrite.
3. **Sealed-eval / append-only-test split.** Builder builds against a visible suite; Critic grades against a hidden one with the same append-only discipline. Right shape for any teach-by-eval setup that fears overfitting — *provided you also enforce the seal physically*, which this repo openly admits it does not yet.
4. **PreToolUse meta-guards.** `guard-meta-writes.ps1` blocks the bootstrap path by which a restricted subagent could escalate. When you restrict an agent's tools, also restrict its ability to *unrestrict itself by editing its own config*.
5. **Three-state heartbeat model.** Distinguish "mtime advancing, content frozen" (zombie) from "mtime stale, PID alive" (busy) from "mtime stale, PID dead" (truly dead). Came from real incidents; portable to any agent-supervision system.

## Closing observation

The hermeneut named it best: the charter is a **constitution**, written in present-imperative ("Build a Creatures-style artificial life simulation") with no subject, addressing whoever happens to be reading. It pins five things ("the triad — fixed, not fungible") that the loop is structurally forbidden from changing. The actual product is the loop's own continued operation. The artificial life is a calibration target, not an end.

Whether one reads that as principled or doctrinaire — whether the elaborate governance is the thesis or self-inflicted noise — is the single interpretive choice that reorganizes everything else in the panel's reviews.

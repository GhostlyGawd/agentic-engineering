# Coherentist Review — norns-loop

## Contradictions

**1. "Three Windows Terminal panes" vs three plain consoles.**
- README.md:34 — *"Three Windows Terminal panes open side-by-side, one per role."*
- start-loop.ps1:47–62 — *"Three plain consoles rather than wt.exe panes so the launcher works on machines without Windows Terminal installed."* Implementation uses `Start-Process -FilePath "powershell.exe"` per role.
- Source of truth: start-loop.ps1. README has drifted.

**2. CHARTER §2 project-root path vs reality.**
- CHARTER.md:13 — *"No writes outside the project root (D:\tmp\omc-test-a)."*
- Actual root: `D:\GitHub Projects\Studies\norns-loop-study\norns-loop`. stop-loop.ps1:25 still hard-codes `$projectMarker = "omc-test-a"` to match processes, so stop-loop will fail silently against the real project tree. Since CHARTER is "immutable, hash-pinned," this is a load-bearing contradiction: the hash-locked truth doesn't match the filesystem.

**3. Network-guard module: `sitecustomize.py` vs `_netguard.py`.**
- README.md:25 — *"`sitecustomize.py` monkey-patches `socket` to whitelist only github.com."*
- MILESTONES.md:88 references *"the sitecustomize-allowed path"* and *"the sitecustomize guard catches it."*
- Filesystem: no `sitecustomize.py` exists; `_netguard.py` is the actual module, loaded explicitly by `conftest.py` and `norns/__init__.py`. `_netguard.py:1` even describes itself: *"Loaded EXPLICITLY by importers — not via site.py auto-discovery."* README/MILESTONES are stale.

**4. Network whitelist: "only github.com" vs three hosts.**
- README.md:25 — *"whitelist only github.com"*
- CHARTER.md:12 — *"`git push`, `git fetch`, `gh` CLI to api.github.com"*
- _netguard.py:5 — `_ALLOWED_HOSTS = {"github.com", "api.github.com", "codeload.github.com"}` plus loopback.
The three documents each give a different allow-list.

**5. Builder "must never read .sealed/" — claimed enforcement is absent.**
- CHARTER.md:17 — *"The Builder agent must never read `.sealed/`."*
- README.md:22 — *"The Builder physically cannot read the suite it's being graded against."*
- start-loop.ps1:19–24 contradicts this directly: *"Day 0 model: all three sessions share the project root (single working tree). Per-role worktrees are a future hardening target (physical .sealed/ seal)."*
- guard-meta-writes.ps1 blocks **writes** to meta-files but has no rule blocking **reads** of `.sealed/`. session-start.ps1:112 admits this: *"The directory exists in this working tree (Day 0 model uses a single tree), but reading it is a charter violation."*
The enforcement is policy-only (Critic post-hoc review); README's *"physically cannot read"* claim is false.

**6. Sprint mirror file is stale.**
- governance/SPRINTS/current.md:23–25 says T-301 *"still blocked on user T-301 action."*
- governance/SPRINTS/sprint-003.md:7–13 says *"T-301 CLOSED cycle 66"* and sprint-003 has progressed through T-310 seed (cycle 77).
current.md's footer also says *"Last refreshed cycle 44"* while sprint-003 is at cycle 77. PROTOCOL implies current.md is the watchdog's mtime probe; orchestrator.py:192–197 reads `current.md` mtime for sprint_age — so PM has been refreshing mtime without refreshing content, exactly the "zombie heartbeat" pattern the orchestrator now also tries to detect for heartbeats.

## Numeric inconsistencies

**1. Test count.**
- README.md:79 — *"# 1. Full test suite (109 cases as of T-013)"*
- sprint-003.md:874 — *"Visible-test count: > 164 at HEAD"* (sprint-002 baseline).
- sprint-003.md:485 cites *"244 passed"* at T-307, then *"256 passed"* at T-308, then *"263 passed"* at T-309. README's 109 is a stale M1 number.

**2. CHARTER §7 token thresholds vs hook implementation.** Coherent.
- CHARTER.md:42–44: 200k handoff, 250k abort.
- user-prompt-submit.ps1:56–61: 250k, 200k, plus a 180k pre-warning. The 180k warning is additive — not contradictory but not in the charter.

**3. Watchdog freshness window.**
- orchestrator.py:54 — `STALE_HEARTBEAT_RESTART_SECONDS = 180  # 3x the 60s tick`
- orchestrator.py:316 — `WATCHDOG_TICK_SECONDS * (_STUCK_SAMPLE_COUNT + 1)` = 240s for the zombie check (sample count=3).
- test_orchestrator_stuck_detection.py:243–285 explicitly tests the widened 240s window vs *"old `* 3`"* 180s. Two different freshness thresholds coexist for two different triggers — internally consistent, but the comment on line 54 (*"3x the 60s tick"*) describes the OLD design; same constants now used in two regimes.

## Definitional drift

- **"sitecustomize"** — used in README/MILESTONES as the file name; the actual file is `_netguard.py` and `conftest.py` loads it as an explicit import. The term is now metaphor, not file.
- **"sealed eval"** — CHARTER.md:23 says Critic *"runs sealed evals + property tests via dispatched subagents"*; MILESTONES.md:86–88 says the eval *"walks the source tree and the running process"*; ROADMAP.md:70 says it just *"passes"*. Compatible at high level, but the eval is treated alternately as a single property test, a multi-clause contract, and an oracle.
- **"D-009 / fetch-only / idle-poll"** referenced 8+ times in sprint-003.md as "BINDING" but not defined in any file I read; DECISIONS.md was not opened, but the cross-references treat D-009 as load-bearing despite the term appearing freely.

## Cross-cutting concern audit

**A. The sealed-read rule (charter → hooks → launcher → tests).**
CHARTER.md:17 declares a hard constraint. session-start.ps1:112 reduces it to instruction. guard-meta-writes.ps1 does not police reads. start-loop.ps1:19–24 admits the constraint is satisfied only by *"Critic's security-reviewer subagent dispatched per commit"* — i.e. behavioural, not physical. README.md:22's *"physically cannot read"* is the strongest claim and the most wrong. The four files describe four different versions of the same rule.

**B. CHARTER §6 stuck-state and 2-failed-recovery rule.**
CHARTER.md:37–38 describes a specific recovery chain: PM diagnose → propose → Critic gate → execute → on 2 failed recoveries hard-pivot. orchestrator.py implements stuck-state *detection* via STUCK_STATE/triggers (sprint_age, veto_streak, stuck_iteration, stuck_last_action, verdict_latency, zombie_heartbeat) but encodes **no concept of "failed recovery"**, no counter, and no hard-pivot mechanism. The PM session is expected to satisfy the rule from the human side; nothing in code enforces it.

**C. Commit prefix discipline (README's table).**
README.md:9–17 enumerates `[pm] [builder] [critic-approved] [critic-veto] [handoff] [orchestrator]`. sprint-003.md narrates *"`[user-action] T-301: …`"* (line 175), `[critic-approved]` and `[pm]` consistently. The `[user-action]` prefix is not in README's table — drift between the public spec and active usage.

## Likely silent inconsistencies

- **`norns/__init__.py:8`** exports only `World, render_frame, Agent`. sprint-003.md:54 visible exit criterion: *"`python -c "from norns import Brain, seeded_array_rng"` succeeds (T-315 closes this AC)"*. T-315 is unclosed; sprint declares the exit criterion still pending. Coherent today, but the README's M2 section is silent about M3 surface despite M3 being three weeks in.
- **`_netguard.py` allows `codeload.github.com`** which CHARTER does not authorise — a real future audit hit if a sealed eval ever enumerates "exactly the charter-permitted hosts."
- **orchestrator.py:51** — `STALE_CLAIM_SECONDS = 30 * 60` and BACKLOG.md:13 sizes tasks for *"~30-90 minutes of work"*. A legitimately long Builder task will hit the reaper's 30-minute claim window before completing.
- **probe.md** is a stale dev-only agent ("Delete after the probe report is in hand") still committed alongside the production code-editor agent.

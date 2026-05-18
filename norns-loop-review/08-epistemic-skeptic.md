# Pyrrhonist Skeptic Review — norns-loop

Suspending judgment on every load-bearing claim. The questions below quote the claim, ask what would justify belief, and rate the evidence I could surface from the repo.

## 1. "The Builder agent must never read `.sealed/`."
`CHARTER.md:17`. The README clarifies the seal is logical, not physical: "Day 0 model: all three sessions share the project root (single working tree)" (`start-loop.ps1:19`). The Builder's session-start prompt at `.claude/hooks/session-start.ps1:112` simply *tells* the Builder not to read it. **How is this enforced?** The pre-commit hook (`scripts/githooks/pre-commit:58-67`) blocks staging `.sealed/`, but does not block *reading* it. The defense reduces to: (a) instruction in a prompt, (b) Critic post-hoc grep. Both are post-violation, not preventive. **Rating: ASSERTED, performatively enforced.** The phrase "physically cannot read" in `README.md:23` is contradicted by `start-loop.ps1:19`.

## 2. "Pre-commit hash check rejects modifications to existing test files."
`README.md:24`. **Does the hook actually run?** The hook lives at `scripts/githooks/pre-commit`, not at `.git/hooks/pre-commit`. I searched the repo for `core.hooksPath`/`git config core.hooksPath` and found zero references. `.git/config` (lines 1-13) has no `hooksPath` entry. **How do you know git invokes this file at all?** Even if it does, it depends on `.sealed/test-hashes.json`, which is gitignored — so the hook only fires if the local clone has populated `.sealed/`. **And `git commit --no-verify`?** The hook comment (`pre-commit:3`) says "Bypassable only with --no-verify (which CHARTER.md forbids the loop from using)" — i.e., bypassable. **Rating: PERFORMATIVE.** The mechanism is described; no evidence the wiring exists in this checkout.

## 3. "Charter is hash-locked."
`README.md:24`. The orchestrator does check (`orchestrator.py:89-103`), and the pre-commit hook checks again (`pre-commit:7-23`). **How often?** Once per 60s `WATCHDOG_TICK_SECONDS` (`orchestrator.py:53`). **Recovery on drift?** It writes `CHARTER_VIOLATION.md` and `sys.exit(2)`. The orchestrator self-exits — but who restarts the loop? `orchestrator.py:21-23` says the orchestrator "does NOT self-exit on halt" — except `verify_charter` calls `sys.exit(2)`, which contradicts the docstring. **Which is right?** **Rating: PARTIALLY DEMONSTRATED, with an internal contradiction about halt semantics.**

## 4. "No network access except `git push`, `git fetch`, `gh` CLI."
`CHARTER.md:12`. The guard is `_netguard.py:5` whitelisting `{"github.com", "api.github.com", "codeload.github.com"}`. `CRITIC_WATCHLIST.md:21` admits: "sealed eval `eval_02_no_network.py` ... does NOT enumerate the full whitelist — a Builder could append `evil.example` to `_ALLOWED_HOSTS` and the eval would still pass." **Show me the test that catches a violation.** `tests/test_netguard.py` (13 lines) asserts only that `socket.getaddrinfo.__name__ == "_guarded_getaddrinfo"` and that `example.com` raises. **What about `urllib3` opening a raw `socket.socket().connect()`?** `_netguard.py` patches `getaddrinfo` and `create_connection` only — not `socket.socket.connect`. **Rating: ASSERTED.** A motivated bypass is a one-line edit the visible eval does not catch.

## 5. "The triad must exist."
`CHARTER.md:24`. **What does "exist" mean operationally?** If the Critic's PowerShell window closes mid-loop, is the triad still existing? `orchestrator.py:465` drops a restart flag on stale heartbeat; `process_restart_flags` re-spawns. **But during the gap?** Builder commits land in `awaiting-critic/`; no Critic verdict gates them. `incident-002-critic-verdict-backlog.md` documents exactly this failure mode in production. **Rating: PERFORMATIVE.** "Exist" is a wish, not a property the orchestrator enforces atomically.

## 6. "Same `--seed` always produces byte-identical `--snapshot-out` JSON."
`README.md:94-95`. `README.md:116` weakens this to "across re-runs on the same host." **What about across Python minor versions, hash-randomization, OS line endings?** Grep for `PYTHONHASHSEED` returns no matches. `test_world_determinism.py:5-11` only checks two `World(seed=42)` instances in the same process, not byte identity of serialized output across processes. `test_snapshot_json_roundtrip` checks JSON round-trip, not byte-identity. **Rating: ASSERTED for same-process; UNTESTED across-process, across-platform.**

## 7. "109 cases as of T-013."
`README.md:80`. **Still 109?** `incident-003-sealed-eval-vs-task-spec-conflict.md:15` says "visible 118/118"; `critic-overrule-002-T-201.md:48` says "126/126"; the test file count I enumerated under `tests/` is 41 files. **The README has not been updated.** What's the actual current count? **Rating: STALE.** The "as of T-013" hedge is honest; the foreground number is not.

## 8. "Each commit is prefixed by the role that produced it."
`README.md:7`. **Is this enforced or claimed?** The pre-commit hook (`scripts/githooks/pre-commit`) does not check commit-message prefixes. No `commit-msg` hook exists. **Could a session forge a prefix?** Trivially — it's a free-form string the role types. **Rating: CONVENTION, NOT ENFORCED.**

## 9. "The Critic must have veto over 'done' claims."
`CHARTER.md:18`. **Evidence of an exercised veto?** GitHub commits review of the most recent 30 commits shows **zero `[critic-veto]` prefixes**. The two retros titled "critic-overrule" (001 and 002) are both cases where the Critic *overruled* its own subagent's veto and approved anyway. **Has any builder commit ever been blocked by a Critic veto reaching `main`?** The two `[critic-approved]` commits I sampled both pass through. `governance/queue/done/` shows 50+ `.approved.json` files; I see no `.vetoed.json` in `done/`. **Rating: PERFORMATIVE.** The mechanism exists; the historical record shows the Critic approving its own overruled vetoes, not vetoing Builder work.

## 10. Bonus: "The Builder physically cannot read the suite it's being graded against." (`README.md:23`)
Directly contradicted by `start-loop.ps1:19-24`: "all three sessions share the project root (single working tree). Per-role worktrees are a future hardening target." **Rating: FALSE AS STATED.** The seal is procedural.

## 11. Bonus: `_netguard.py` only patches two functions
`_netguard.py:40-41` patches `getaddrinfo` and `create_connection`. **What about `socket.socket().connect((ip, port))` directly?** Not patched. **`http.client.HTTPConnection` over a raw IP?** Not caught by hostname check, only by the loopback exception which would let through any IP literal. Actually, `_is_allowed` returns True for loopback IPs only — a literal `8.8.8.8` would be rejected. But the *socket.socket().connect()* path bypasses both patched functions entirely. **Rating: PARTIAL.**

## Three Questions That Would Most Change the Plan

1. **"Show me `git config --get core.hooksPath` output from a fresh clone."** If the pre-commit hook isn't wired, then the entire append-only-tests guarantee and the duplicate charter-hash check both collapse to advisory text. This is the single highest-leverage question.
2. **"Show me the commit hash of the last `[critic-veto]` that blocked a Builder commit from reaching `main`."** If there isn't one, the Critic's veto authority is theoretical and the loop's anti-reward-hacking story rests on a button that has never been pressed.
3. **"Run the netguard suite while also calling `socket.socket(AF_INET, SOCK_STREAM).connect(('1.2.3.4', 80))`. Does it raise?"** Resolves whether the network claim is policy or mechanism.

## The Smoothest Passage

> "**Sealed evals.** `.sealed/` is gitignored. Only the Critic session's worktree contains it. The Builder physically cannot read the suite it's being graded against." — `README.md:22-23`

Three sentences, three knowledge claims, zero qualifications. It reads as a fait accompli — and it is the claim most flatly contradicted by `start-loop.ps1:19` ("Day 0 model: all three sessions share the project root (single working tree). Per-role worktrees are a future hardening target"). Smooth prose hides the gap between "physically cannot" and "is instructed not to." A skeptic should distrust any passage that achieves rhetorical closure faster than its underlying mechanism does.

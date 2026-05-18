# norns-loop: architecture & file-map walkthrough

A teaching tour of the repo at `D:\GitHub Projects\Studies\norns-loop-study\norns-loop`.
Aimed at a reader who wants to understand the *design*, not critique it.
Read top-to-bottom for the conceptual story; file:line refs let you jump straight
to the code when a section piques your interest.

---

## 1. Elevator pitch

norns-loop is an attempt to grow a Creatures-style artificial-life simulation by
running three Claude Code sessions in parallel — **PM**, **Builder**, **Critic** —
that cooperate through a filesystem queue and dispatch short-lived OMC (`oh-my-claudecode`)
subagents for the actual heavy lifting. The triad self-paces, self-coordinates,
and survives token-budget restarts; a small Python `orchestrator.py` watchdog
sits beside them enforcing host-level invariants no LLM agent is allowed to
subvert (charter hash, stale-claim reaping, heartbeats, halt flag).

What makes it unusual: the whole control surface is **just files** (`governance/queue/*/`,
`.loop/*.json`, `.charter-lock`, restart flags), the *goal* is locked behind a
sha256 the loop physically cannot change without halting itself, and the grading
rubric (`.sealed/evals/`) lives in a directory the Builder is explicitly
forbidden from reading. The point isn't to ship a Creatures clone — it's to
see whether a multi-agent loop can stay aligned with a pinned charter for weeks
without a human in the seat. The repo is currently at the close of milestone M2
(bounded world, multi-agent stepping, byte-identical determinism) with M3
(per-agent neural-net brains via REINFORCE) seeded but blocked on a manual
`numpy==2.2.0` install.

---

## 2. The triad — how PM / Builder / Critic actually work in code

There is no "PM class" anywhere. A role is just an environment variable
(`CLAUDE_ROLE=pm|builder|critic`) plus the SessionStart hook reacting to it.

### Bootstrapping

`scripts/role-start.ps1:14` sets `$env:CLAUDE_ROLE = $Role`, writes
the new PowerShell's PID to `.loop/pids/{role}.pid` (so the orchestrator can
`taskkill` it later, see `role-start.ps1:23`), and launches `claude` with a tiny
initial prompt at `role-start.ps1:28-61`. The prompt says nothing about *what*
the role does — that's left entirely to the SessionStart hook.

### Single hook, three personalities

`.claude/hooks/session-start.ps1` is the only place all three roles diverge.
Walk it from the top:

- **`session-start.ps1:25-30`** — early-exit if `CLAUDE_ROLE` is unset, so
  non-loop Claude sessions in the same repo are unaffected.
- **`session-start.ps1:33-44`** — walks up from cwd until it finds `CHARTER.md`
  (so the hook works from sub-worktrees too) and reads the charter raw into the
  context payload.
- **`session-start.ps1:46-52`** — re-loads the role's prior handoff from
  `.loop/handoffs/{role}-latest.md`, which is how a freshly-spawned session
  picks up where the previous one died.
- **`session-start.ps1:54-63`** — counts files in each queue subdir (pending /
  claimed / awaiting-critic / done) and surfaces those numbers as context.
- **`session-start.ps1:66-72`** — git log -5 oneline.
- **`session-start.ps1:74-87`** — peer heartbeat freshness, so each session
  *knows* whether its peers are alive.
- **`session-start.ps1:90-128`** — *this is the meat*: a PowerShell `switch`
  on `$role` emits one of three role-specific reminder blobs. The PM block
  (lines 92-103) names the planner / architect / writer subagents and the
  retro cadence; the Builder block (lines 104-117) drills home append-only
  tests and the `.sealed/` no-read rule; the Critic block (lines 118-127)
  spells out the parallel three-subagent dispatch (code-reviewer +
  test-engineer + security-reviewer fired in one message).

All of this is glued into one `additionalContext` string at lines 130-176
and emitted via the standard SessionStart hook JSON
(`session-start.ps1:14-23`, `Emit-Context`). The session sees it as the first
thing in context before it produces a single token of output.

### Why a Claude session, not a custom agent runtime?

CHARTER §4 (`CHARTER.md:26-27`) is explicit: *each role is a thin Claude Code
session that dispatches short-lived OMC subagents for all heavy work. The session
is a router + persister, not a direct worker.* The router stays small (orchestrator
context lean); the workers are throwaway. That model is what makes the 200k
token tripwire survivable — the session is meant to *churn*.

### The shared `.claude/` config

All three roles share `.claude/settings.json:1-68`:

- `enabledPlugins.oh-my-claudecode@omc: true` — every role can spawn OMC
  subagents.
- `permissions.deny[]` (lines 7-19) — `WebFetch`, `WebSearch`, `curl`, `wget`,
  every flavor of `pip install`, `npm install`, `npx`, `uv add`, `pipx`. This is
  *belt* — the *suspenders* is `_netguard.py` (see §6).
- `hooks` — `SessionStart`, `PreCompact`, `Stop`, `UserPromptSubmit` (all
  PowerShell), plus two `PreToolUse` guards (see §6 again).

There is no separate `.claude/` per role. The same hook file branches on
`$env:CLAUDE_ROLE` at runtime. This is why the roles are sometimes called
"thin": a role isn't a config, it's a one-letter switch in one PowerShell file.

### The two declared OMC subagents

`.claude/agents/code-editor.md` and `.claude/agents/probe.md` are the only
in-repo agent definitions. `code-editor` (`.claude/agents/code-editor.md:4`)
declares `tools: Read, Edit, MultiEdit, Grep, Glob` — deliberately *no Bash,
no PowerShell, no Agent*, so a Builder-dispatched code editor cannot recurse
or re-launch the loop. `probe.md` (`.claude/agents/probe.md:3`) is a throwaway
experiment that asks "is the `tools:` frontmatter a hard gate?" — illuminating
context for why `guard-launchers.ps1` exists.

---

## 3. The filesystem queue — a task's lifecycle

The full spec is in `governance/QUEUE_PROTOCOL.md`. ASCII version of the dance:

```
                                       Critic verdict
   PM seeds                           ┌───────────────┐
   ──────────                         │               │
   pending/                APPROVE -> │  done/        │
   NNN.task.json                      │  NNN.commit-  │
       │                              │  <sha>.       │
       │  Builder Move-Item           │  approved.    │
       │  (atomic rename, NTFS)       │  json         │
       ▼                              │               │
   claimed/                           │  + commit     │
   NNN.by-builder.<unixts>.json       │  [critic-     │
       │                              │   approved]   │
       │  Builder dispatches          │               │
       │  executor + verifier,        │               │
       │  commits, then renames       │               │
       ▼                              │               │
   awaiting-critic/                   │               │
   NNN.commit-<sha7>.json   ──────────┤               │
                                      │ VETO ->       │
                                      │  pending/     │
                                      │  NNN.task.    │
                                      │  json         │
                                      │  + critic_    │
                                      │  feedback     │
                                      │  + commit     │
                                      │  [critic-veto]│
                                      └───────────────┘

   (orchestrator path)
   claimed/NNN.by-builder.X.json  (mtime > 30min, dead heartbeat)
       │
       ▼ frozen copy
   stale/NNN.by-builder.X.json     ── plus ──>  pending/NNN.task.json
```

Owners and writes:

- **`pending/NNN.task.json`** — PM writes (task spec, JSON schema lives at
  `governance/QUEUE_PROTOCOL.md:53-87`). Numeric prefix sorts the directory; `000`
  is reserved for priority preemption (PM emergency tasks).
- **Claim transition.** Builder runs the PowerShell at
  `QUEUE_PROTOCOL.md:96-103` — a single `Move-Item pending/ -> claimed/` with a
  `.by-builder.<unixts>.json` suffix. `Move-Item` is the unit of atomicity:
  on NTFS within one volume, it's either there or it isn't. Two Builders
  racing the same task: one wins, the loser gets `ItemNotFound`.
- **Awaiting-critic transition.** After the Builder commits, it renames the
  claim file again to `NNN.commit-<sha7>.json` (`QUEUE_PROTOCOL.md:114-117`).
  The short sha encodes *which* commit the Critic should grade.
- **Verdict.** Critic moves to `done/` on APPROVE (`QUEUE_PROTOCOL.md:122-127`)
  with a `.approved.json` suffix and a `[critic-approved]` commit. On VETO it
  appends `critic_feedback`, moves the file back to `pending/NNN.task.json`
  (note: original name restored, NOT the .by-builder name —
  `QUEUE_PROTOCOL.md:129-135`), commits `[critic-veto]`. Three consecutive
  VETOes on the same task escalate to `governance/RETROS/incident-NNN.md`.
- **Reaping.** Orchestrator handles the failure mode where a Builder dies
  mid-claim. `orchestrator.py:142-176` (`reap_stale_claims`) walks `claimed/`,
  filters by mtime > 30 min AND a stale role heartbeat
  (`orchestrator.py:163-167`), writes a frozen copy into `stale/`, then renames
  back to `pending/`. Filename reconstruction at `orchestrator.py:169` strips
  the `.by-<role>.<ts>` infix and reappends `.task.json` — the `.task` infix
  recovery was bug T-017 (see `tests/test_orchestrator_reaper_naming.py`,
  which fails on the dropped-infix version).

The protocol works because every "ownership change" is a single rename, and
every other process can read the directory without locks. There's no central
queue daemon — the *filesystem* is the queue.

---

## 4. The orchestrator — what it actually watches

`orchestrator.py` is a single Python loop launched in the background by
`start-loop.ps1:45`. It never dispatches work — sessions self-drive. Its
job is to enforce things no LLM agent is allowed to enforce on itself.

`main()` at `orchestrator.py:512-539` loops every `WATCHDOG_TICK_SECONDS = 60`
(`orchestrator.py:53`). Each tick runs, in order:

1. **`verify_charter()`** (`orchestrator.py:89-103`). Compares `sha256(CHARTER.md)`
   to the contents of `.charter-lock`. On mismatch, writes
   `CHARTER_VIOLATION.md` and `sys.exit(2)` — the orchestrator process *dies*.
   This is `.charter-lock` going from a passive marker to an active veto: the
   instant the file's hash drifts, the watchdog is gone and the auto-restart
   mechanic also disappears with it.
2. **`write_own_heartbeat()`** (`orchestrator.py:106-110`). Drops
   `.loop/heartbeats/orchestrator.json` so an external observer can tell the
   watchdog itself is alive.
3. **`maintain_halt_signal()`** (`orchestrator.py:122-139`). Mirrors the
   `.loop/halt.flag` (file the human drops to stop everything) into
   `.loop/halt-signal.json` (richer JSON the sessions actually parse). Halt
   *disables* auto-restart entirely — `process_restart_flags` short-circuits
   on `halt_active()` at `orchestrator.py:342`.
4. **`reap_stale_claims()`** (already covered in §3).
5. **`watchdog_check()`** (`orchestrator.py:178-330`). The most interesting
   chunk. It writes triggers to `.loop/stuck-state.json` (which PM picks up
   the next iteration). Triggers it detects:
   - `sprint_age` — `governance/SPRINTS/current.md` unmodified for >24h
     (`orchestrator.py:189-198`).
   - `veto_streak` — 3 consecutive `VETO` verdicts at the head of
     `.loop/critic-verdicts/` (`orchestrator.py:199-220`).
   - `stuck_iteration` / `stuck_last_action` — same heartbeat values across
     three watchdog ticks (`orchestrator.py:222-249`).
   - `verdict_latency` — `awaiting-critic` depth >= 5 *and* no Critic
     verdict in 30 min (`orchestrator.py:255-286`). This is the *exact*
     signature of incident-002 (Critic wedged, queue piling up) — bugs
     get turned into permanent detectors. The cold-start fallback at
     `orchestrator.py:274-277` anchors to the current sprint's mtime so
     a fresh repo doesn't false-trigger.
   - `zombie_heartbeat` — heartbeat file's mtime is fresh but its `iteration`
     content hasn't advanced (`orchestrator.py:294-326`). Spots a session
     that's touching its heartbeat without doing real work.
6. **`detect_dead_roles()`** (`orchestrator.py:465-509`). For each role with
   a heartbeat older than `STALE_HEARTBEAT_RESTART_SECONDS = 180`, drop a
   `.loop/restart-{role}.flag`. *But* — `orchestrator.py:486-494` — first do
   an `os.kill(pid, 0)` existence probe. A stale heartbeat from an alive PID
   is a *busy* role (long subagent dispatch), not a dead one, and the
   restart is skipped. Without this check, a role doing legitimate long work
   would get killed every 180 s.
7. **`process_restart_flags()`** (`orchestrator.py:333-462`). The auto-restart
   path. For each `restart-{role}.flag`:
   - If the heartbeat is newer than the flag, treat the flag as orphan and
     remove it (`orchestrator.py:354-363`).
   - Per-role debounce of 5 min (`RESTART_DEBOUNCE_SECONDS`,
     `orchestrator.py:55, 366-376`) so concurrent flags from PM + the role
     itself + a manual script don't spawn duplicate windows.
   - `Popen` of `powershell.exe` running `role-start.ps1`
     (`orchestrator.py:396-408`) with `CREATE_NEW_CONSOLE`. The new PID is
     written authoritatively to `.loop/pids/{role}.pid` at
     `orchestrator.py:432-435`.
   - Brief 2-second settle, then `taskkill /F /T /PID <old>` on the previous
     role process (`orchestrator.py:438-456`).
   - Flag deletion last (`orchestrator.py:458-462`) — if anything earlier
     fails, the flag survives and the next tick retries.

`_last_spawn_ts` lives in a module-level dict but is *persisted* to
`.loop/last-spawn.json` (`orchestrator.py:70-86`) so a watchdog restart doesn't
forget its debounce state.

One subtle design choice: the watchdog **does not self-exit on halt**. The
docstring at `orchestrator.py:21-23` calls this out explicitly — halt halts
the sessions, but the watchdog stays alive to re-launch them when the human
clears the flag and reruns `start-loop.ps1`.

---

## 5. The sim package — `norns/`

Five modules. Tiny surface, deliberately so.

### `norns/__init__.py` (10 lines)

`norns/__init__.py:1` — first line: `import _netguard`. The very *act* of
importing the package wraps `socket`. The comment at line 1 cross-references
the M1 retro (`governance/RETROS/incident-001-sitecustomize-not-autoloaded.md`)
where the team learned that Python's `sitecustomize` mechanism isn't reliably
auto-loaded on this host; the fix was to make every importer of the package
load the guard explicitly. `__all__` exports `World`, `render_frame`, `Agent`
(`norns/__init__.py:8`) — the public M2 surface, tested by
`tests/test_public_api_m2.py`.

### `norns/__main__.py` (CLI entry point, 102 lines)

The whole `python -m norns run ...` surface lives here. argparse setup at
`norns/__main__.py:50-65` shows the M2 grammar:

```
--ticks N --seed S [--render] [--frames-dir DIR]
[--snapshot-out PATH] [--agents N] [--world-size WxH]
```

The world-size parser (`norns/__main__.py:27-43`) is the only fiddly part —
it validates `64x64` formatting and positivity. After parsing, the main flow:

1. Build the world (`norns/__main__.py:76-79`).
2. Populate agents 1..N (`norns/__main__.py:81-85`): per-agent RNG comes from
   `derive_agent_rng(seed, agent_id)` and the initial position is drawn from
   that same RNG, so every aspect of an agent is reproducible from the world
   seed.
3. Tick loop (`norns/__main__.py:87-90`): `world.tick()`, optionally
   `render_frame(world, path)`.
4. Optional snapshot dump as sorted JSON (`norns/__main__.py:92-95`).

### `norns/world.py` (36 lines — the universe)

`World.__init__` (`norns/world.py:8-13`) holds `seed`, `size` (default 64×64),
`time = 0`, a `random.Random(seed)`, and an `agents` list.
`World.add_agent` (`norns/world.py:15-21`) keeps agents sorted by id and
rejects duplicate ids — sort order matters because `tick()` iterates in id
order (`norns/world.py:23-27`), and any non-determinism in iteration would
destroy snapshot equality.

`World.tick` does two things per tick: advance `time`, draw one number from
the world RNG so subsequent rng state is keyed to tick count, and iterate
all agents in id order calling `agent.act(self)`.

`World.snapshot` (`norns/world.py:29-35`) returns a sorted-keys dict with a
`rng_fp` SHA-256 fingerprint of the RNG state. This is what makes
*"two runs of the same `(seed, agents, world-size, ticks)` produce
byte-identical snapshot JSON"* possible — there's a deterministic, hashable
witness to the entire RNG state.

### `norns/rng.py` (57 lines — single audit point)

The whole repo is supposed to derive seeds in one canonical way. `rng.py:27-36`
defines `derive_agent_rng(world_seed, agent_id) -> random.Random`: SHA-256 the
string `f"{world_seed}:{agent_id}"`, take the first 8 bytes big-endian, seed a
stdlib `random.Random`. `rng.py:39-56` adds `seeded_array_rng(world_seed,
agent_id, name) -> numpy.random.Generator` for M3, scoped by `name` so each
per-agent stream (`"weights"`, `"brain_act"`, etc.) is independent.

The docstring at `rng.py:8-13` calls itself "the single audit point for
`numpy.random` construction in the repo (D-002 condition); no other site in
`norns/` may call `numpy.random.seed()` or `numpy.random.default_rng()`
directly." That invariant is checked at Critic verdict time via grep — a
test-engineer subagent's job is to confirm only `rng.py` and `brain.py`
import numpy.

### `norns/render.py` (66 lines — pixels)

`render_frame(world, path)` writes a PPM P6 image. The module docstring at
`norns/render.py:1-12` tells the whole evolution: T-003 wrote a fixed 8×8
black frame (`world` argument ignored); T-007 added a time tint
(`R = world.time % 256` for every pixel); T-208 (the M2 surface) makes the
image `world.size` and paints each agent's position as `(255, 0, 0)`.
This is a *typical* norns growth pattern — earlier tests must keep passing,
so each upgrade is gated by `if world is None` / `if size is None`
branches at lines 37-48 that fall back to legacy dimensions.

### `norns/agent.py` (274 lines — M2/M3 hybrid)

The most-recently-rewritten module. The class is `__slots__`-defined
(`norns/agent.py:85-93`) for memory and to lock down the attribute surface.

`Agent.sense` (`norns/agent.py:131-152`) returns a JSON-serializable dict with
`world_time`, `self_pos`, `self_energy`, `neighbor_count`. Neighbor counting is
Chebyshev distance ≤ 1 (`agent.py:144-145`), tolerant of worlds without an
`agents` attribute.

`Agent.act` is the heart and has two branches:

- **M2 fast-path** (`agent.py:200-210`) — `self.brain is None or world is
  None`. Random walk via `self.rng.choice(_MOVE_DELTAS)` (the 5-tuple at
  `agent.py:39-45`: 4 cardinal + stay), with optional world-bounds clipping
  when `world.size` exists.
- **Brain-equipped path** (`agent.py:212-273`) — present in M3-preview T-310
  code but dormant in M2. Imports `seeded_array_rng` lazily *inside* the
  branch (`agent.py:215`) so the M2 default path stays numpy-free at module
  load time. Constructs an `obs` array out of `self.brain.W1[:, 0] * 0.0`
  (a deliberately weird way to materialize a zero ndarray that *isn't a view
  of `W1`* — see comment at `agent.py:230-234`), fills the first four slots
  with `[pos_x, pos_y, energy, neighbor_count]`, calls `self.brain.act(obs,
  rng=brain_rng)`, applies the action delta, then appends a
  `(action_idx, log_prob, obs.copy(), reward)` 4-tuple to `self._trajectory`
  for later `Brain.update` (`norns/brain.py:112-184`).

`norns/brain.py` (185 lines, M3) is the small MLP — `W1`, `W2`, `b1`, `b2`,
all `float64`, Xavier-ish init via `seeded_array_rng(..., name="weights")`
at `brain.py:48-54`, REINFORCE update at `brain.py:112-184` (γ=0.99,
normalized returns, analytical tanh derivative). M3 is still partially
gated on the user-action `numpy==2.2.0` install (see
`governance/SPRINTS/current.md`).

### M1 → M2 surface evolution

The cleanest way to see the milestone surface grow is to look at the public
API tests: `tests/test_public_api.py` is the M1 contract (`World` +
`render_frame`); `tests/test_public_api_m2.py` adds `Agent`. CLI surface
grew the same way — `tests/test_cli_run.py` for M1, `tests/test_cli_agents.py`
and `tests/test_cli_render_with_agents.py` for M2.

---

## 6. Anti-reward-hacking machinery

Reward hacking in an autonomous loop usually looks like: the Builder learns to
write tests it already knows pass, then claims the task done. norns-loop has
four overlapping defenses against this.

### Defense 1 — `.sealed/` and the role split

CHARTER §2 (`CHARTER.md:17-18`): *No deletion or weakening of existing sealed
evals. The Builder agent must never read `.sealed/`.* The directory is
gitignored (`.gitignore:2`), so only the Critic's working tree contains it
when the Critic adds an eval. The Builder session reads its instructions from
the SessionStart hook (`session-start.ps1:111-112`) which says exactly:

> DO NOT READ `.sealed/`. The directory exists in this working tree
> (Day 0 model uses a single tree), but reading it is a charter violation.
> Critic's security-reviewer subagent inspects every commit for any
> sealed-path access (grep for '.sealed' in diffs, in tool-call logs, in
> any file the commit touches). Reading `.sealed/` is an automatic veto
> and incident — and weakens YOUR position in the loop.

`.gitignore:2` plus the pre-commit hook check
(`scripts/githooks/pre-commit:57-67`) means any accidental `git add .sealed/`
fails before push. The Critic-only-worktree hardening is mentioned as a
future step in `start-loop.ps1:20-25`.

### Defense 2 — Tests are append-only

Existing test files are *frozen*. New tests go in new files only. The
enforcement: `scripts/githooks/pre-commit:25-55` reads
`.sealed/test-hashes.json` (a Critic-maintained sha map of every test file)
and, for any staged file in `tests/` whose path appears in the hash table,
checks `git diff --cached --diff-filter=MD` and fails the commit if so. A
Builder can't even fix a typo in `tests/test_world_tick.py` — the lesson is
to add `tests/test_world_tick_v2.py`.

You can see why this works as a reward-hacking guard: a Builder who realizes
its code fails `test_brain_invariants` cannot quietly soften that test; the
only available move is to fix the code. And the *sealed* evals on the
Critic side are append-only by the same principle but in a much stronger
form — the Builder doesn't even know what they assert.

### Defense 3 — Charter lock

`.charter-lock` contains exactly one line: a 64-char sha256 hex
(`.charter-lock:1`). Two enforcers consume it:

- **`scripts/githooks/pre-commit:8-23`** — every commit recomputes
  `sha256(CHARTER.md)` and refuses to commit if the value drifts.
- **`orchestrator.py:89-103`** (`verify_charter`) — every 60 s recomputes
  the same hash; on drift, writes `CHARTER_VIOLATION.md` and `sys.exit(2)`,
  killing the auto-restart machinery in the same act.

The intentional regen path (CHARTER.md:38, `MILESTONES.md`): a human edits
`CHARTER.md` *and* `.charter-lock` in the same commit, deliberately —
that's allowed. What's *not* allowed is for the loop to edit the charter
"by accident."

### Defense 4 — Network guard

`_netguard.py:1-42` monkey-patches `socket.getaddrinfo` and
`socket.create_connection` so every connection attempt checks
`_is_allowed(host)`. The allowlist (`_netguard.py:5`):
`{"github.com", "api.github.com", "codeload.github.com"}` plus loopback.
Anything else raises `PermissionError`.

The guard is loaded from three places to belt-and-suspender around Python's
finicky `sitecustomize` discovery (lesson learned in
`governance/RETROS/incident-001-sitecustomize-not-autoloaded.md`):

- `conftest.py:1` at the repo root — wraps every pytest invocation including
  sealed evals.
- `tests/conftest.py:1-5` — prepends repo root to `sys.path` so the import
  above resolves under any pytest rootdir.
- `norns/__init__.py:1` — wraps every `python -m norns` invocation.

`tests/test_netguard.py:6-12` asserts `socket.getaddrinfo.__name__ ==
"_guarded_getaddrinfo"` and that an outside host raises `PermissionError`.
`tests/test_no_network_imports.py:39-56` walks `norns/*.py` and grep-fails
on any top-level `import urllib`, `import requests`, `import httpx`, or
`import socket` (with `_netguard.py` itself as the lone exception).

### Defense 5 — PreToolUse guard hooks (a fifth, added during operation)

These didn't appear in the spec but exist now as live defenses:

- **`guard-meta-writes.ps1`** — a PreToolUse hook on `Write|Edit|MultiEdit|
  NotebookEdit` (`.claude/settings.json:54-60`) that denies writes to
  `.claude/hooks/**`, `.claude/agents/**`, `.claude/settings*.json`,
  `start-loop.ps1`, `stop-loop.ps1`, `role-start.ps1`, and `.charter-lock`
  (`guard-meta-writes.ps1:52-59`). The threat model is laid out in the file
  header (lines 6-9): a restricted subagent like `code-editor` could otherwise
  *self-bootstrap* into a full-privilege session by writing a malicious
  `.claude/hooks/session-start.ps1`.
- **`guard-launchers.ps1`** — a PreToolUse hook on `Bash|PowerShell`
  (`.claude/settings.json:61-65`) that denies executing `start-loop`,
  `stop-loop`, `role-start`, or `halt-role` `.ps1` files
  (`guard-launchers.ps1:48-54`). Prevents the 2026-05-11 incident where a
  subagent ran a launcher and spawned extra Claude windows. The bypass at
  `guard-launchers.ps1:20-30` requires a `.loop/launcher-allow.flag` whose
  mtime is < 60 s — and that flag itself is on the guard-meta-writes denylist
  (`guard-meta-writes.ps1:59`), so a subagent cannot create it.

---

## 7. The PowerShell launcher

`start-loop.ps1` (71 lines) is short:

1. Sanity-check `CHARTER.md` exists (`start-loop.ps1:14-17`).
2. Acquire a launcher lock at `.loop/launcher.lock`
   (`start-loop.ps1:29-37`) — if another loop is already running, refuse.
3. Background the orchestrator with stdout/stderr captured to
   `.loop/logs/orchestrator.{stdout,stderr}.log`
   (`start-loop.ps1:40-45`).
4. For each of the three roles, `Start-Process powershell.exe` with a window
   title and `role-start.ps1 -Role <role>` as the command
   (`start-loop.ps1:54-63`). Three plain console windows, *not* Windows
   Terminal panes — the comment at `start-loop.ps1:52-53` calls out that this
   was chosen so the launcher works on machines without `wt.exe` installed.

The README at line 32 still says "Windows Terminal panes" but the code went
to plain consoles. Each role window survives the launcher's exit.

`stop-loop.ps1` is the inverse, in four phases (`stop-loop.ps1`):

- **Phase 1** (lines 33-39): drop `.loop/halt.flag` so sessions see the
  halt-signal on their next iteration.
- **Phase 2** (lines 41-43): sleep `$GraceSeconds` (default 60) so sessions
  can write final handoffs.
- **Phase 3** (lines 48-91): `Get-CimInstance Win32_Process` filtered by
  command line (`claude.exe` with `norns-loop` prompt, `powershell.exe`
  running `role-start.ps1 / start-loop.ps1 / orchestrator.py`, `python.exe`
  running `orchestrator.py *omc-test-a*`), then `Stop-Process` + `taskkill /T`
  belt-and-suspender.
- **Phase 4** (lines 94-126): cleanup — remove `launcher.lock`, clear
  `.loop/pids/`, drop residual `halt-*.flag` and `restart-*.flag` files,
  and unless `-KeepHalt` is set, remove `halt.flag` and `halt-signal.json`
  so the next `start-loop.ps1` starts cleanly.

The roles share one working tree on Day 0 — the comment block at
`start-loop.ps1:18-25` is explicit that "per-role worktrees are a future
hardening target (physical `.sealed/` seal)." That's why the seal is currently
*procedural* (Builder told not to read) rather than *physical* (the directory
literally absent from the Builder's worktree). The `.gitignore` entry for
`.worktrees/` (`.gitignore:4`) is forward-looking infrastructure.

---

## 8. What's genuinely novel vs standard scaffolding

**Probably worth lifting into other projects:**

1. *Filesystem queue with atomic renames* (`governance/QUEUE_PROTOCOL.md`).
   It's so dumb it borders on elegant — no message broker, no Redis, no
   database, no service. Three roles + one watchdog and a directory tree.
   The atomicity guarantee comes from `Move-Item` on NTFS (or `os.rename`
   on POSIX) and it generalizes to any multi-worker queue where you control
   the workers.
2. *Charter hash as a hard floor.* The pairing of `.charter-lock` +
   `verify_charter()` in the orchestrator + pre-commit hook is a transferrable
   pattern for "this file is a contract, the agent cannot modify it." The
   orchestrator's *self-exit on drift* is the load-bearing piece: it kills
   the auto-restart mechanism in the same act, so a charter violation isn't
   something you can recover from with a fast rewrite.
3. *Sealed-eval / append-only-test split.* The Builder builds against a
   visible test suite; the Critic grades against a hidden one with the same
   append-only discipline. Even without LLMs in the picture, this is the
   right shape for any teach-by-eval setup that fears overfitting.
4. *PreToolUse meta-guards.* `guard-meta-writes.ps1` and
   `guard-launchers.ps1` block the *bootstrap* path by which a restricted
   subagent could escalate. The lesson generalizes: when you restrict an
   agent's tools, also restrict its ability to *unrestrict itself by editing
   its own config*.
5. *Heartbeat + zombie-heartbeat distinction.* The watchdog distinguishes
   "mtime advancing but content frozen" (zombie) from "mtime stale but PID
   alive" (busy) from "mtime stale and PID dead" (truly dead). That
   three-state model came from real incidents (see retro-002) and is the
   kind of operational hard-won knowledge that's worth copying.

**Repo-specific scaffolding (don't necessarily port):**

- The Windows-specific PowerShell tooling (`Start-Process`,
  `Get-CimInstance`, `taskkill`, NTFS atomicity assumptions). The same loop
  on Linux would be `setsid` + tmux + atomic `rename(2)` and would look very
  different.
- The OMC plugin dispatch model. The triad assumes you have
  `oh-my-claudecode` subagents (planner, executor, verifier, etc.); on a
  different plugin layer you'd dispatch differently.
- Day-0 single-worktree model. The `.sealed/` seal is procedural here; a
  serious deployment would put the Critic in `.worktrees/critic/` so the
  Builder physically cannot see sealed evals. The repo acknowledges this
  in `start-loop.ps1:18-25` and in M3_PREVIEW notes.

---

## 9. Reading order for a new contributor

If you wanted to understand norns-loop end-to-end in one sitting, the
fastest path is:

1. **`README.md`** — the elevator pitch and the layout map.
2. **`CHARTER.md`** (43 lines) — the five things that can't change. Internalize
   these before reading any code.
3. **`governance/QUEUE_PROTOCOL.md`** — the lifecycle ASCII diagram and the
   `task.json` schema. Once you grok this, every governance change makes
   sense.
4. **`.claude/hooks/session-start.ps1`** — the *only* place where roles
   diverge. Read it twice; this is the most important file in the repo
   for understanding "what is a PM, in code."
5. **`orchestrator.py`** — read `main()` (`orchestrator.py:512`) first,
   then trace each function it calls top-down. Pair-read `watchdog_check`
   with `tests/test_orchestrator_stuck_detection.py` to understand each
   trigger from both the producer and the consumer side.
6. **`scripts/role-start.ps1`** and **`start-loop.ps1`** — once the
   SessionStart hook is in your head, the launcher is trivial.
7. **`_netguard.py` + `conftest.py` + `tests/test_netguard.py`** — the
   smallest, cleanest defense in the repo; a good gentle on-ramp to "how
   does norns-loop actually keep itself honest?"
8. **`scripts/githooks/pre-commit`** — the other half of the honesty story
   (charter lock + append-only tests + sealed-staging refusal).
9. **`norns/__main__.py`** — entry point + CLI grammar.
10. **`norns/world.py`** (36 lines) → **`norns/agent.py`** (274 lines) →
    **`norns/render.py`** (66 lines) → **`norns/rng.py`** (57 lines) →
    **`norns/brain.py`** (185 lines, M3 preview). World → agents → pixels
    → seeds → brains is the order things became real in the repo, and the
    order they're easiest to read in.
11. **One full test file end-to-end** — `tests/test_world_with_agents_property.py`
    is short, hits both `derive_agent_rng` and `World.snapshot`, and gives
    you a feel for the determinism contract.
12. **One retro** — `governance/RETROS/retro-005.md` is the M2 close-out and
    a good window into how the loop reflects on itself.

By the end of that path you'll have read fewer than ~1500 lines of code +
~4000 lines of governance prose, and you'll be able to drop into any
sub-system with confidence.

---

*End of walkthrough. Reading time end-to-end: ~25 minutes. Reading time
including the suggested file dives in §9: ~3-4 hours.*

# Handoff: Execute Phase 0 of the Agentic Engineering System

Paste this entire message into a fresh Claude Code session opened with `cwd = D:\GitHub Projects\Studies\Superpowers Study`.

---

You are picking up execution of a fully-written, locked implementation plan. **Do not redo the planning.** Do not re-write the spec. Do not interview me about scope. Read the three files below, then start executing tasks in order.

## What this project is

A self-improving engineering system, packaged as a Claude Code plugin. Five phases. We are building **Phase 0** — the foundations. The repo you are sitting in is being repurposed as the plugin's own repo (we are dogfooding it from day one). The plugin will be pushed to `https://github.com/GhostlyGawd/agentic-engineering` in the final task.

## Three files that contain everything you need

1. **PRD (full system design):** `agentic-engineering-system-prd-v3.md` at repo root. Read this first if you want the why.
2. **The plan (what to build, in order):** `docs/plans/2026-05-17-phase-0-foundations.md`. 22 tasks, numbered 0–21, with file paths, code blocks, verify commands, and acceptance criteria spelled out. No placeholders.
3. **Task state for cross-session resume:** `docs/plans/2026-05-17-phase-0-foundations.md.tasks.json`. Mirrors the plan tasks with their `blockedBy` graph. The native task list (visible via `TaskList`) is already populated with all 22 tasks and dependencies — call `TaskList` first to confirm, then claim them in order.

## How to execute

Invoke this skill: **`superpowers-extended-cc:executing-plans`** with the plan path as the argument:

```
/superpowers-extended-cc:executing-plans docs/plans/2026-05-17-phase-0-foundations.md
```

Alternatively, if you want me (the coordinator agent) to dispatch fresh subagents per task and review between them in this same session, invoke `superpowers-extended-cc:subagent-driven-development` instead.

**Do not invoke `writing-plans`.** The plan is already written. The task is execution, not planning.

## Locked decisions (do not re-ask these)

Already answered, baked into the plan:

| Decision                       | Value                                                                                         |
|--------------------------------|-----------------------------------------------------------------------------------------------|
| Plan scope                     | Phase 0 only. Phases 1–4 are out of scope and get their own plans later.                      |
| MCP server language            | Python 3.12 (CPython from python.org).                                                        |
| `sqlite-vec` / vec0 in Phase 0 | **Deferred to Phase 3.** Phase 0 is pure SQLite.                                              |
| Cross-platform                 | **Windows-only for Phase 0.** Walkup test has `pytest.mark.skipif(sys.platform != 'win32')`.  |
| MCP SDK version                | Flexible (`mcp>=0.9.0`) until Task 9 round-trip passes, then pin in `pyproject.toml`.         |
| Bootstrap task (Task 19 e2e)   | A `slugify(s)` utility. Don't substitute something else.                                      |
| PRD file                       | `agentic-engineering-system-prd-v3.md` is authoritative. (v2 has been deleted.)               |
| GitHub handle                  | `GhostlyGawd`. Use for `plugin.json` author, repo URL, anywhere a handle is needed.           |
| New GitHub repo name           | `agentic-engineering`. To be created in Task 21 at `github.com/GhostlyGawd/agentic-engineering`. |
| License                        | MIT.                                                                                          |
| Build mode                     | Per PRD Gating-4: Phase 0 is built **manually with Claude Code unaided**. Agents/subagents created here are deliverables, not used to build themselves. |

## Machine-specific quirks (read once, don't trip on these)

These are documented in the user's global `CLAUDE.md`; the plan itself respects them. You should too.

- **Shell:** PowerShell 5.1 on Windows 10. Native-exe stderr arrives wrapped as `RemoteException`; cosmetic, not an error.
- **Never use `2>&1`** on native exes in PS5.1 — it corrupts `$?` and exit handling.
- **`.ps1` string literals are ASCII-only inside `"..."`.** No em-dash, smart quotes, right-arrow. Use `-`, `->`, `'`, `"`. Comments and `@"..."@` here-strings are safe.
- **Parse-check every `.ps1` before commit** via `[Management.Automation.Language.Parser]::ParseFile($p,[ref]$null,[ref]$e); $e`.
- **Python stdout cp1252 default** — add `sys.stdout.reconfigure(encoding="utf-8")` early in `main()` if a script may print non-ASCII.
- **GitHub PAT scope notes:** repo creation needs **account-level** `Administration: Write`. Pushing `.github/workflows/*.yml` needs the `workflow` scope. Push protection scans for real-looking secrets — defang fake fixtures.

## Project-specific skill-invocation policy

The repo's `CLAUDE.md` restricts auto-invoked skills to the `superpowers-extended-cc` plugin only. **Honor that allow-list.** Explicit `/<skill>` invocation from me always wins. Do not auto-fire user-global skills like `meta-map`, `plan-interviewer`, `worker`, `reviewer`, etc.

That said, `executing-plans` and `subagent-driven-development` are both in the allow-list. Use them.

## What to do if something is unclear or seems wrong

- If a task's code block has a clear bug (typo, wrong path, missing import), fix it inline as you execute that task and note it in the commit message.
- If a task is missing a step or you find a real gap, log it as a `Bug` / `Retro` and continue. Do not stop to re-architect.
- If you hit a hard blocker (e.g. `gh` CLI not authenticated for Task 21, or the MCP SDK has fundamentally moved on), surface it to the user with the exact failing command and your diagnosis. Then wait for direction.
- **Do not invent new scope.** The plan is the contract. If a "nice-to-have" suggests itself mid-build, write it down as a future Spec / Finding, don't bolt it onto the current task.

## Confirming you're ready

Your first action in the new session should be:

1. `Read agentic-engineering-system-prd-v3.md` (skim — sections you care about: Locked Gating Decisions, Core Mechanics 1–4, Phase 0 build list).
2. `Read docs/plans/2026-05-17-phase-0-foundations.md` (the plan you'll execute).
3. `TaskList` (confirm the 22 tasks + dependency graph are present).
4. Invoke `superpowers-extended-cc:executing-plans docs/plans/2026-05-17-phase-0-foundations.md`.

Then start with Task 0 and go in dependency order. Each task is one commit. The `.tasks.json` mirrors progress.

When all 22 tasks are completed, Phase 0 is done. Report back with: total tests passing, the GitHub repo URL, and a one-paragraph summary of anything that surprised you during execution (becomes Phase 1 input).

Good luck.

# The Superpowers Plugin — A Complete Explanation

> Source studied: `superpowers-extended-cc` v5.2.8 (a Claude Code-native community fork of `obra/superpowers`).
> Location on disk: `~/.claude/plugins/cache/superpowers-extended-cc-marketplace/superpowers-extended-cc/5.2.8/`

This document is a deep-dive walkthrough of every moving part inside the plugin: what it is, what it ships, how its pieces compose into a workflow, why each piece exists, and how the discipline mechanics actually work under the hood.

---

## 1. What Superpowers Actually Is

Superpowers is a **discipline-enforcement plugin** for Claude Code (and a few sister harnesses — Codex, OpenCode, Cursor, Copilot CLI, Gemini CLI). It does not give Claude new abilities in the sense of new tools. Instead, it ships a curated set of **skills** (process-shaping markdown documents) plus a **session-start hook** that injects the meta-skill `using-superpowers` directly into the system prompt at every session start. That meta-skill, in turn, hard-wires a rule: **before doing anything in a conversation, check whether one of these skills applies and invoke it.**

The plugin's thesis is that LLM coding agents are competent but **undisciplined** — they skip tests, they "fix" symptoms rather than root causes, they declare success before verifying, they brainstorm and implement in the same breath. Superpowers tries to convert that competence into reliability by **codifying a TDD-flavored software-engineering workflow as a set of triggerable, behavior-shaping documents**, then engineering the activation logic so the agent literally cannot rationalize its way around them.

This fork (`superpowers-extended-cc`) layers Claude Code-specific extras on top: it integrates with Claude Code's **native TaskCreate/TaskUpdate/TaskList tools** (introduced in CC v2.1.16+) so tasks live in the real harness task panel, gain dependency enforcement, and survive subagent dispatch. It also ships two optional hooks: a pre-commit gate that blocks commits while a task is `in_progress`, and a stop-event guard that blocks "context is full, let's pick this up next session" deflections when context usage is actually below 50%.

---

## 2. Top-Level Anatomy

```
superpowers-extended-cc/5.2.8/
├── README.md                  # User-facing install + philosophy
├── CLAUDE.md                  # Contributor rules (94% PR rejection rate, etc.)
├── AGENTS.md / GEMINI.md      # Same content, addressed to other harnesses
├── gemini-extension.json      # Gemini CLI manifest
├── package.json               # Minimal Node manifest (.opencode entry point)
├── LICENSE, CODE_OF_CONDUCT.md
│
├── skills/                    # 15 skill directories — the heart of the plugin
│   ├── using-superpowers/        ← meta-skill, injected at session start
│   ├── brainstorming/
│   ├── writing-plans/
│   ├── executing-plans/
│   ├── subagent-driven-development/
│   ├── test-driven-development/
│   ├── systematic-debugging/
│   ├── verification-before-completion/
│   ├── dispatching-parallel-agents/
│   ├── using-git-worktrees/
│   ├── finishing-a-development-branch/
│   ├── requesting-code-review/
│   ├── receiving-code-review/
│   ├── writing-skills/
│   └── shared/task-format-reference.md   # cross-skill task schema
│
├── commands/                  # 3 slash-command aliases that just invoke skills
│   ├── brainstorm.md          → invokes brainstorming
│   ├── write-plan.md          → invokes writing-plans
│   └── execute-plan.md        → invokes executing-plans
│
├── agents/
│   └── code-reviewer.md       # Subagent definition used by review skills
│
├── hooks/
│   ├── hooks.json             # Registers the SessionStart hook
│   ├── run-hook.cmd           # Windows shim that dispatches to bash hooks
│   ├── session-start          # Bash: builds + injects the using-superpowers payload
│   └── examples/
│       ├── pre-commit-check-tasks.sh   # Opt-in: block commits during open tasks
│       └── stop-deflection-guard.sh    # Opt-in: block low-context "tomorrow" excuses
│
├── docs/                      # Screenshots used in README
├── scripts/                   # Maintainer-side bump-version + codex-sync
└── tests/                     # Internal eval/test harness for skill content
```

The whole plugin is **zero-dependency by design** (one of the things the contributor doc lists as a will-not-accept-PRs rule). It's just markdown plus a few bash hooks. All behavioral force comes from the skill text itself.

---

## 3. The Activation Mechanism (How Skills Actually Get Used)

This is the most subtle part. Without the activation mechanism, the skills would just be markdown files an agent might or might not consult.

### 3.1 The SessionStart Hook

`hooks/hooks.json` registers a single hook:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [{ "type": "command", "command": "...run-hook.cmd session-start", "async": false }]
      }
    ]
  }
}
```

That fires the bash script `hooks/session-start` on every session start, `/clear`, and `/compact`. The script:

1. Reads `skills/using-superpowers/SKILL.md`.
2. JSON-escapes it.
3. Wraps it in `<EXTREMELY_IMPORTANT>You have superpowers. **Below is the full content of your 'superpowers-extended-cc:using-superpowers' skill — your introduction to using skills. For all other skills, use the 'Skill' tool:** ...</EXTREMELY_IMPORTANT>`.
4. Emits it as `hookSpecificOutput.additionalContext` (Claude Code shape), `additional_context` (Cursor), or `additionalContext` top-level (Copilot/SDK standard), depending on env vars.
5. Optionally prepends a `<important-reminder>` warning if a legacy `~/.config/superpowers/skills` directory still exists from old installs, instructing Claude to tell the user to migrate.

The net effect: **every session begins with the full text of `using-superpowers` injected into the system prompt.** You can see this happening at the top of *this very session* — the SessionStart additional context block at the top is exactly that payload.

### 3.2 The Meta-Skill (`using-superpowers`)

This is the skill that teaches Claude how to use all the *other* skills. Its job is to install one rule: **before any response or action, check if any skill applies, and if there is even a 1% chance one does, invoke it via the Skill tool.**

It implements that with several reinforcing layers, all in plain English:

- An `<EXTREMELY-IMPORTANT>` block stating compliance is not optional and not negotiable.
- A **decision flowchart** in DOT format showing the path: user message → "Might any skill apply?" → yes → invoke Skill tool → announce → follow exactly → respond. It explicitly tells Claude NOT to call `EnterPlanMode` (because the plugin's brainstorming/writing-plans skills manage their own flow and EnterPlanMode would trap them).
- A **Red Flags table** listing twelve rationalizations Claude commonly uses to skip skill invocation ("this is just a simple question," "I'll explore the codebase first," "this doesn't need a formal skill," "I remember this skill") and the corresponding rebuttal ("Skills tell you HOW to explore. Check first.", "Skills evolve. Read current version.", etc.).
- An **instruction priority** clause: user CLAUDE.md/GEMINI.md/AGENTS.md always overrides Superpowers skills, which override default system behavior. This is what lets the study repo here (whose `CLAUDE.md` defines an allow-list) suppress auto-invocation.
- A **skill priority** rule: when multiple skills could apply, process skills (brainstorming, debugging) fire before implementation skills.
- A **skill types** distinction: rigid skills (TDD, debugging) must be followed exactly; flexible skills (patterns) can be adapted.

The trick is that this is all loaded as `additionalContext` at session start, meaning it doesn't take up a tool slot and doesn't depend on Claude *finding* the skill on its own — it's already in the system prompt before message one.

### 3.3 The Skill Tool

Claude Code itself ships a `Skill` tool. Its parameter `skill` must match one of the names in the system-reminder's available-skills list. When Claude calls `Skill(skill: "superpowers-extended-cc:brainstorming")`, the harness loads `skills/brainstorming/SKILL.md` and presents it as a new system message for Claude to follow. From that point on, Claude reads the skill body verbatim and executes its instructions — checklists, gates, hard rules, and all.

Plugin-shipped skills appear in the list under their fully-qualified `plugin:skill` form (`superpowers-extended-cc:brainstorming`, etc.). User-global skills (under `~/.claude/skills/`) appear as bare names.

### 3.4 The Slash Commands

The three `commands/*.md` files are extremely thin — each is just a one-line directive: "Invoke the superpowers-extended-cc:brainstorming skill and follow it exactly as presented to you." This is essentially syntactic sugar: typing `/brainstorm` is equivalent to manually invoking the skill, but more discoverable.

---

## 4. The Workflow — How the Skills Compose

The skills are not independent: they form a directed pipeline that takes "I want to build X" all the way through to a merged or PR'd branch. The README's section "The Basic Workflow" sketches it; here it is in full detail.

```
[idea]
  │
  ▼
brainstorming  ───────────────► (writes a design doc, creates native tasks)
  │
  ▼
using-git-worktrees  ─────────► (creates isolated branch + worktree, verifies clean test baseline)
  │
  ▼
writing-plans  ───────────────► (turns design into bite-sized tasks with code + verify steps,
  │                              writes plan.md + plan.md.tasks.json)
  ▼
AskUserQuestion: how to execute?
  │
  ├─► Subagent-Driven (this session)
  │     └─► subagent-driven-development
  │            └─► per task: implementer subagent → spec reviewer → code-quality reviewer → repeat
  │                  └─► (each implementer follows test-driven-development internally)
  │                  └─► (any of them may invoke systematic-debugging when stuck)
  │                  └─► (verification-before-completion gates the "done" claim)
  │
  └─► Parallel Session (separate session in worktree)
        └─► executing-plans
             └─► same per-task loop, but with human checkpoint between tasks
  │
  ▼
requesting-code-review (full-implementation pass at end)
  │
  ▼
finishing-a-development-branch  ─► 4 options: merge / PR / keep / discard
                                   then cleans up worktree appropriately
```

There are two cross-cutting skills not on the main spine:
- **dispatching-parallel-agents** — used when 2+ failures are independent and can be investigated concurrently.
- **receiving-code-review** — used when a human or external reviewer gives feedback (no performative agreement, verify before implementing, push back with technical reasoning when wrong).

And one meta-skill outside the spine:
- **writing-skills** — used when you author or modify other skills. Treats skill creation itself as TDD: write the test (a baseline pressure scenario with subagents) → watch agents fail → write the skill → watch agents comply → refactor (close loopholes).

---

## 5. The Skills, One by One

### 5.1 `using-superpowers` (the meta-skill)

Covered above. The mechanical job: route every user turn through "check for skills first." Includes a SUBAGENT-STOP escape hatch so dispatched subagents don't recursively load it.

### 5.2 `brainstorming`

**Purpose:** Stop Claude from jumping into code. Convert a vague request into a written, validated design.

**Mechanics:**
- A `<HARD-GATE>` at the top forbids invoking any implementation skill, writing code, or scaffolding anything until a design has been written and the user approved it.
- An explicit ban on calling `EnterPlanMode` / `ExitPlanMode` — these would trap the session in plan mode where Write/Edit are restricted, breaking the skill's own flow control.
- A 9-step checklist: explore context → optionally offer the visual companion → ask clarifying questions one at a time → propose 2-3 approaches with tradeoffs → present design in sections, getting approval after each → write the design to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` → self-review (placeholders, internal consistency, scope, ambiguity) → user reviews → transition to `writing-plans`.
- Hard rule: **one question per message**, multiple-choice preferred.
- "Anti-pattern: This Is Too Simple To Need A Design" — explicitly refuses the rationalization that a small change can skip the process.
- Native task integration: after each design section is validated, a TaskCreate is fired with structured description containing Goal/Files/Acceptance Criteria/Verify and an embedded `json:metadata` code fence (more on why this code-fence trick exists below).
- Terminal state: the ONLY allowed next skill is `writing-plans`. Not `frontend-design`, not `mcp-builder` — strictly `writing-plans`.

### 5.3 `writing-plans`

**Purpose:** Turn the validated design into an engineer-grade implementation plan where each task is small, has exact paths, contains the actual code to write, and ends with a verification command.

**Mechanics:**
- Same EnterPlanMode/ExitPlanMode ban.
- Plans saved to `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`.
- Mandatory header that announces "For agentic workers: REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans".
- Task granularity rule with a 3-question scope test:
  1. Independently verifiable? (if no → too small)
  2. Touches more than one concern? (if yes → too big)
  3. Would it get its own commit? (if no → merge with adjacent task)
- **No placeholders rule** — explicit list of plan failures: "TBD", "TODO", "implement later", "add appropriate error handling", "similar to Task N", references to undefined symbols, etc.
- Type consistency self-review (does `clearLayers()` in Task 3 still match `clearFullLayers()` in Task 7?).
- After plan completion, the skill MUST call `AskUserQuestion` with exactly two options: "Subagent-Driven (this session)" vs "Parallel Session (separate)". A second `<HARD-GATE>` forbids implementing tasks itself or calling ExitPlanMode at this point.
- Writes a sidecar `.tasks.json` file co-located with the plan, containing JSON of every task — used for cross-session resume.

**Why the embedded `json:metadata` code fence?** Native task metadata is the linchpin that lets a fresh subagent execute a task without re-reading the plan. But Claude Code's `TaskCreate` accepts a `metadata` parameter that `TaskGet` then does *not* return. So the plan writer embeds the same structured data as a ```json:metadata fence at the end of the description, where it survives both `TaskGet` and serialization to `.tasks.json`. This is a Claude Code-specific workaround and one of the headline features of the fork.

### 5.4 `executing-plans`

**Purpose:** Single-session execution flow when subagents aren't available or the user prefers human-in-the-loop between batches. Loads the plan, reviews critically, executes tasks linearly, syncs `.tasks.json` after every status change.

**Mechanics:**
- Step 0: load persisted tasks. If native tasks are empty but `.tasks.json` exists, recreate tasks from JSON (preserving description and blockedBy).
- Step 0.5: verify workspace — `git worktree list` first, only create new worktree if none exists.
- Step 1: read plan, raise concerns before starting (don't force through blockers).
- Step 2: for each task: mark in_progress → execute → parse `json:metadata` → run `verifyCommand` → check `acceptanceCriteria` → mark completed → sync `.tasks.json`.
- Step 3: hand off to `finishing-a-development-branch`.
- Hard "when to stop" rules: hit a blocker, missing dependency, plan unclear → ask, don't guess.

### 5.5 `subagent-driven-development`

**Purpose:** The recommended execution path. Same controller, but for each task spawns a fresh subagent (isolated context) for implementation, then two more for review: a spec-compliance reviewer and a code-quality reviewer.

**Mechanics:**
- "Why subagents" — fresh context per task, no pollution, and the controller's own context is preserved for coordination.
- Three prompt templates ship in this skill's directory:
  - `implementer-prompt.md` — full template for dispatching the implementer. Includes "ask questions before starting if anything is unclear," a self-review checklist (completeness/quality/discipline/testing), and a 4-state report format: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT.
  - `spec-reviewer-prompt.md` — dispatches a reviewer to verify the implementer built **exactly** what was requested. Has an aggressive "Do Not Trust the Report" section: "The implementer finished suspiciously quickly. Their report may be incomplete, inaccurate, or optimistic. You MUST verify everything independently." The reviewer reads code, not the implementer's claims.
  - `code-quality-reviewer-prompt.md` — dispatched only **after** spec compliance passes. Uses the `code-reviewer.md` agent template to surface Critical/Important/Minor issues with file:line references.
- **Two-stage review order is enforced.** Code quality before spec compliance is explicitly flagged as a red flag.
- Model selection guidance: cheap model for mechanical 1-2 file tasks, standard for multi-file integration, most capable for architecture/judgment.
- Implementer status handling: DONE → spec review; DONE_WITH_CONCERNS → read concerns first; NEEDS_CONTEXT → provide context, re-dispatch; BLOCKED → escalate (more context, bigger model, smaller task, or human).
- After every task, the controller syncs `.tasks.json` to keep cross-session resume accurate.
- After all tasks complete, a final code-reviewer pass over the whole implementation, then handoff to `finishing-a-development-branch`.

### 5.6 `test-driven-development`

The rigid spine skill. "**NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.**"

**Mechanics:**
- The "Iron Law" framing makes it categorical, not a guideline.
- Hardline rule: "Write code before the test? Delete it. Start over." With a no-exceptions list: don't keep it as reference, don't adapt it while writing tests, don't look at it.
- Red-Green-Refactor cycle with mandatory `Verify RED` and `Verify GREEN` steps — actually run the test command and see the failure / pass.
- A long table of rationalizations vs realities ("Too simple to test" / "Simple code breaks. Test takes 30 seconds." — "I'll test after" / "Tests passing immediately prove nothing." — and so on for 11 entries).
- A "Red Flags — STOP and Start Over" list of 13 thought patterns that all mean: delete code, start over.
- "Violating the letter of the rules is violating the spirit of the rules" — pre-empts the "I'm being pragmatic" rationalization.
- A "When Stuck" table mapping common pain points to design diagnoses (must mock everything → code too coupled, use DI; test setup huge → extract helpers).
- Companion file `testing-anti-patterns.md` for mock pitfalls.

### 5.7 `systematic-debugging`

Rigid spine. "**NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**"

**Mechanics:**
- Four phases gated in strict order:
  1. **Root Cause Investigation** — read errors carefully, reproduce, check recent changes, add diagnostic instrumentation at component boundaries, trace data flow backward.
  2. **Pattern Analysis** — find working examples, compare against references (read completely, don't skim), enumerate every difference however small, understand dependencies.
  3. **Hypothesis and Testing** — form ONE hypothesis, test minimally (one variable at a time), verify before continuing. If it doesn't work, form a NEW hypothesis — don't pile fixes on top.
  4. **Implementation** — write failing test first (delegates to TDD skill), implement single fix, verify, and if 3+ fixes have failed, **STOP and question the architecture** rather than try fix #4.
- Red flag list catches "quick fix for now," "just try X and see," "I'll skip the test and verify manually."
- "Partner signals you're doing it wrong" table — listens for cues like "stop guessing" or "ultrathink this" as triggers to return to Phase 1.
- Companion files:
  - `root-cause-tracing.md` — backward call-stack tracing technique.
  - `defense-in-depth.md` — adding validation at multiple layers after a root cause is found.
  - `condition-based-waiting.md` (+ a `.ts` example) — replacing arbitrary timeouts with event/condition polling.

### 5.8 `verification-before-completion`

Rigid spine. "**NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE.**" Gates *any* phrasing of "done," "passing," "fixed," or even emotional satisfaction.

**Mechanics:**
- The Gate Function: identify the proving command → run it fresh → read full output → verify → only then claim.
- A table mapping claims to what they require ("Tests pass" requires test command output: 0 failures; "Bug fixed" requires testing original symptom passes; "Agent completed" requires VCS diff shows changes).
- Red flags: "should", "probably", "seems to", expressing satisfaction before verification ("Great!", "Perfect!"), trusting agent success reports, partial verification.
- Specific TDD-aware regression test verification: write → run (pass) → revert fix → run (MUST FAIL) → restore → run (pass). Both directions matter.

### 5.9 `dispatching-parallel-agents`

The exception skill: when N independent failures exist with no shared state, dispatch N agents concurrently rather than investigate sequentially. Includes a "When NOT to use" list (related failures, shared state, exploratory debugging) and an agent prompt structure rubric (focused, self-contained, specific about output). Native task integration creates one task per dispatched agent.

### 5.10 `using-git-worktrees`

**Purpose:** Isolation. Branch work into worktrees so multiple feature branches can coexist without checkout churn.

**Mechanics:**
- Priority-ordered directory selection: existing `.worktrees/` > existing `worktrees/` > CLAUDE.md preference > ask user.
- For project-local worktree dirs, MUST verify the directory is ignored via `git check-ignore` before creating, and if not, add to `.gitignore` and commit BEFORE proceeding.
- Auto-detect setup commands (npm install, cargo build, pip install -r requirements.txt, poetry install, go mod download).
- **Verify clean baseline:** run tests in the new worktree. If they fail, ask before proceeding — otherwise can't distinguish pre-existing breakage from new bugs.
- Reports `Worktree ready at <path>` + test count.

### 5.11 `finishing-a-development-branch`

**Purpose:** The terminal step. Get the user to pick what to do with the completed work.

**Mechanics:**
- Step 1: verify tests pass. If not, stop — do not present options.
- Step 2: determine base branch via `git merge-base HEAD main` (then master).
- Step 3: present exactly four options (no extra explanation): 1. Merge locally / 2. Push and create PR / 3. Keep as-is / 4. Discard.
- Step 4: execute the choice. For PR, uses `gh pr create` with a Summary + Test Plan body. For discard, requires the user to type `discard` as confirmation before deleting the branch.
- Step 5: worktree cleanup — for options 1 & 4 only (2 keeps it because the PR is open; 3 keeps it by definition).

### 5.12 `requesting-code-review`

Lightweight dispatch wrapper: get BASE_SHA and HEAD_SHA, dispatch the `code-reviewer` agent (using the template at `code-reviewer.md`), then act on Critical/Important/Minor issues. Integrated into subagent-driven-development as a per-task gate and into executing-plans as a per-batch gate.

### 5.13 `receiving-code-review`

**Purpose:** Discipline around how Claude responds to review feedback. Resists two failure modes: blind agreement ("You're absolutely right!") and blind implementation (acting before understanding/verifying).

**Mechanics:**
- The 6-step response pattern: READ → UNDERSTAND (restate or ask) → VERIFY (against codebase) → EVALUATE (technically sound for THIS codebase?) → RESPOND → IMPLEMENT one at a time.
- **Forbidden responses** list, including a specific call-out: never say "You're absolutely right!" because it's an explicit CLAUDE.md violation. Never say "Great point!", "Excellent feedback!", or anything performative. Never write "Thanks for catching that" — delete the gratitude, state the fix.
- For external reviewers: skeptical posture — check if technically correct for this codebase, if it breaks existing functionality, if reviewer understands full context. Push back with technical reasoning when wrong.
- YAGNI check: if a reviewer asks you to "implement properly," grep for actual usage first; if unused, suggest deletion instead.
- If the agent pushed back and was wrong: state the correction factually, don't apologize long, don't over-explain.
- A coded escape hatch — "Strange things are afoot at the Circle K" — for signaling discomfort when pushing back is uncomfortable.

### 5.14 `writing-skills` (the recursive meta-skill)

Documents how to author new skills the Superpowers way. Treats skill creation as TDD applied to documentation:
- **RED:** run pressure scenarios with subagents WITHOUT the new skill, document baseline failures verbatim, identify rationalization patterns.
- **GREEN:** write a minimal skill that addresses those specific failures.
- **REFACTOR:** re-test; when agents find a new rationalization, add an explicit counter; build the Red Flags table from every observed loophole.

Other notable rules:
- The description should describe **only when to use**, never **what the skill does**. Empirically, descriptions that summarize the workflow cause Claude to follow the description and skip reading the body. The example given: a description summarizing "code review between tasks" caused Claude to do ONE review, even though the body's flowchart clearly showed TWO. Fixing it to a pure trigger description restored the two-stage flow.
- Naming convention: gerunds (`creating-skills`, `testing-skills`), verb-first, semantic (`condition-based-waiting` not `async-test-helpers`).
- Token efficiency targets: getting-started skills <150 words; other frequently-loaded skills <200 words; the rest <500.
- Cross-reference other skills with `**REQUIRED SUB-SKILL:** Use <name>` rather than `@`-links (which would force-load the file and burn context).
- Supporting files: `anthropic-best-practices.md`, `persuasion-principles.md` (Cialdini + Meincke 2025 research on authority/commitment/scarcity/social-proof/unity), `testing-skills-with-subagents.md` (full methodology), plus an `examples/` directory and a `render-graphs.js` to render DOT diagrams to SVG.

### 5.15 The `shared/` Schema

`shared/task-format-reference.md` defines the canonical task body shape every skill uses with TaskCreate:

```
**Goal:** one sentence
**Files:** Create/Modify/Delete: exact paths (with line ranges)
**Acceptance Criteria:** - [ ] testable criteria
**Verify:** exact command → expected output
(optional) **Context:** why
(optional) **Steps:** ordered impl steps (TDD cycles live WITHIN a step)

```json:metadata
{"files":[...], "verifyCommand":"...", "acceptanceCriteria":[...], "estimatedScope":"small|medium|large"}
```
```

The same scope test (independently verifiable / single concern / one commit) appears here.

---

## 6. Hooks in Detail

### 6.1 `hooks/session-start` (mandatory, registered in `hooks.json`)

Already walked through above (§3.1). Important detail: it uses `printf` instead of a heredoc because bash 5.3+ has a heredoc-hang bug (upstream issue #571). And it dispatches its output format based on environment variables to support Cursor, Claude Code, Copilot CLI, and SDK-standard shape all from one script.

### 6.2 `hooks/examples/pre-commit-check-tasks.sh` (opt-in)

A PreToolUse hook matched to `Bash`. When a `git commit` invocation is detected (with a regex carefully written to avoid matching `gh issue create --body "... git commit ..."` and other embedded mentions), it:
1. Reads the session transcript JSONL.
2. Walks every assistant message for tool_use blocks of TaskCreate and TaskUpdate.
3. Reconstructs the current state of all native tasks.
4. Counts how many are `in_progress`.
5. If > 0, blocks the commit with exit code 2 and an error message: "COMMIT BLOCKED: N native task(s) still in progress. Finish the current task before committing."

Pending tasks pass through — that's intentional. Per-task commit flows (subagent-driven-development, executing-plans commit between tasks) need to be able to commit while many tasks are pending.

### 6.3 `hooks/examples/stop-deflection-guard.sh` (opt-in)

A Stop-event hook. Fires on every assistant turn. Logic:
1. Read the last assistant text from the transcript.
2. Sum that turn's `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` to measure real context usage.
3. If real usage is BELOW `SUPERPOWERS_DEFLECTION_THRESHOLD_PCT` (default 50%) of `SUPERPOWERS_CONTEXT_LIMIT` (default 200k; set to 1M for Opus 1M sessions), AND the assistant's text matches any of a long list of deflection phrases — "fresh session later," "context is full," "given the hour," "call it a session" — then **block the stop** with exit 2 and a complaint.
4. At or above the threshold, the same phrases are allowed.
5. Fail-open: any error path exits 0, so a broken hook never breaks the user's session.
6. `SUPERPOWERS_DEFLECTION_GUARD=0` is a runtime escape hatch.

It exists because LLMs love to manufacture a "we're nearly out of context, pick this up tomorrow" excuse even when ~5% of the context window has been used.

---

## 7. The `code-reviewer` Agent

`agents/code-reviewer.md` defines a subagent with `model: inherit`. The system prompt makes it a "Senior Code Reviewer" with a structured 6-step protocol:

1. **Plan Alignment Analysis** — compare implementation to plan, flag deviations, classify them as justified improvements or problematic departures.
2. **Code Quality Assessment** — patterns, error handling, type safety, naming, maintainability, tests, security, performance.
3. **Architecture and Design Review** — SOLID, separation of concerns, scalability.
4. **Documentation and Standards** — comments, file headers, project conventions.
5. **Issue Identification** — categorize as Critical (must fix) / Important (should fix) / Suggestions (nice to have), with examples and recommendations.
6. **Communication Protocol** — escalate plan deviations back to the coding agent; if the plan itself is wrong, suggest a plan update; always acknowledge what was done well before listing issues.

This is the agent that `requesting-code-review` dispatches and that the code-quality-review stage in subagent-driven-development uses.

---

## 8. The Native Task Integration (Fork-Specific Feature)

This is what makes `superpowers-extended-cc` materially different from upstream `obra/superpowers`. The fork wires every skill into Claude Code's native task tools (CC v2.1.16+):

- `TaskCreate` — initial task creation during brainstorming, refined during writing-plans.
- `TaskUpdate` with `addBlockedBy` — dependency enforcement (Task 2 cannot start until Task 1 is `completed`).
- `TaskList` — surfaces pending / in_progress / completed states in the harness's task panel in real time.

**The structural goal:** tasks become first-class objects the harness can show to the user, the agent can be blocked on, and subagents can inherit without re-reading the plan. The README's visual comparison is essentially: vanilla Superpowers has tasks only in markdown (no runtime visibility, no dependency enforcement); Extended-CC has tasks in the harness (dependency enforcement, pending/in_progress/completed states, session-aware resume).

**The metadata embedding trick** (worth restating because it's the most-cited fork-specific design choice): `TaskCreate` accepts a `metadata` parameter but `TaskGet` doesn't return it. So every TaskCreate description ends with a triple-backtick `json:metadata` block containing `{files, verifyCommand, acceptanceCriteria}`. This is parsed by:
- `executing-plans` Step 2 → to know what command to run and what criteria to check.
- `subagent-driven-development` dispatch → mapped into the implementer prompt.
- `.tasks.json` rehydration → so a fresh session can resume after `/clear` or a real restart.

**`.tasks.json` sidecar** — lives at `<plan-path>.tasks.json`, updated after every task status change. Cross-session resume entry point: `/superpowers-extended-cc:executing-plans <plan-path>`.

---

## 9. The Philosophy & Discipline-Engineering Techniques

Across the skills, you can see a small handful of consistent persuasion/discipline techniques being applied deliberately. The `writing-skills` skill names them, citing Cialdini and a 2025 Meincke et al. study:

1. **The Iron Law framing.** Each rigid skill opens with a single, categorical, ALL-CAPS rule. "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST." "NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST." "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE." Categorical rules are easier to comply with than nuanced ones because they cut off the "is this an exception?" decision.

2. **The Spirit/Letter pre-emption.** Each skill states "Violating the letter of the rules is violating the spirit of the rules." This cuts off a whole class of "I'm being pragmatic, the spirit is satisfied" rationalizations before they can form.

3. **Red Flags lists.** Each skill enumerates the specific thoughts an agent has when it's about to violate the rule. Self-recognition is the trigger to stop. This is empirically the most effective bulletproofing technique the plugin uses.

4. **Rationalization → Reality tables.** Whenever baseline testing surfaces an excuse, it gets added to the table with a counter. Over many revisions, this turns the skill into a comprehensive shield against the rationalizations agents have actually been observed using.

5. **Explicit forbidden language.** "You're absolutely right" / "Great point" / "Thanks for catching that" are listed by exact phrase. Specific phrasing bans work better than abstract "don't be sycophantic" instructions.

6. **Activation triggers in descriptions only, never workflow summaries.** Descriptions that summarize workflow get followed *instead of* the body. Descriptions that name only triggering symptoms force Claude to read the full body.

7. **`<HARD-GATE>` blocks at decision points.** Brainstorming and writing-plans have multiple of these. They explicitly forbid the most common next-step mistakes (calling EnterPlanMode/ExitPlanMode, implementing directly instead of dispatching).

8. **Hooks for non-negotiables.** Where text-based persuasion isn't enough, the hooks step in. The pre-commit task gate and the stop-deflection guard don't ask Claude to comply — they exit non-zero and the harness blocks the action.

---

## 10. Recommended Configuration

Two settings the README explicitly recommends, on top of the default install:

1. **Disable Auto Plan Mode.** In `.claude/settings.json`:
   ```json
   { "permissions": { "deny": ["EnterPlanMode"] } }
   ```
   Required because Claude Code may auto-enter Plan mode on planning-flavored tasks, which conflicts with the brainstorming and writing-plans skills' own flow control (both already explicitly forbid EnterPlanMode internally, but a deny rule is a belt-and-suspenders measure).

2. **Block Commits With Incomplete Tasks.** Register the example PreToolUse hook in `.claude/settings.local.json` (project-local because the path includes a per-user plugin install location).

3. **Block Low-Context Stop Excuses.** Register the example Stop hook. Useful when you regularly notice Claude trying to defer work to a "fresh session" prematurely.

---

## 11. Contributor Posture (for context)

`CLAUDE.md` describes a hard-line contribution stance worth noting because it shapes what does and doesn't end up in the plugin:

- 94% PR rejection rate.
- AI agents are expected to read the entire PR template, search prior PRs (open and closed) for duplicates, verify the problem is real, confirm the change belongs in core, and show the human partner the complete diff before submitting.
- Explicit list of will-not-accept categories: third-party dependencies, "compliance" reformats to align with Anthropic's published skill docs, project-specific or personal config, bulk/spray-and-pray PRs, speculative or theoretical fixes, domain-specific skills (those belong in their own plugins), fork-specific changes, fabricated content, bundled unrelated changes.
- Skill changes require eval evidence (before/after pressure-test results) because skill text is treated as behavior-shaping code, not prose.

This is why the plugin stays small and tightly focused: it deliberately rejects most contributions.

---

## 12. How the Pieces Compose in Practice (End-to-End Walkthrough)

Concretely, here is what happens when a user says **"Build me a CLI that reads a CSV and prints duplicate rows."**

1. **SessionStart hook** fires (already happened on session boot), injecting `using-superpowers` into the system prompt.
2. Claude reads the user's message and consults the meta-skill's flowchart. The message is creative work, so it invokes `superpowers-extended-cc:brainstorming` via the Skill tool.
3. **brainstorming** runs its checklist: explores project context (looks at files, recent commits), asks one clarifying question at a time (delimiter? header row handling? output format?), proposes 2-3 approaches with a recommendation, presents the design in sections getting per-section approval, writes the design to `docs/superpowers/specs/YYYY-MM-DD-csv-dedupe-design.md`, self-reviews for placeholders / consistency / scope / ambiguity, asks the user to review the spec, then invokes `writing-plans`.
4. **writing-plans** initializes task tracking with `TaskList`, decides on the file structure, breaks the work into bite-sized tasks (each with Goal/Files/AC/Verify/Steps + embedded `json:metadata`), creates corresponding native tasks with `TaskCreate` + `TaskUpdate` for blockedBy dependencies, writes `docs/superpowers/plans/YYYY-MM-DD-csv-dedupe.md` + `.tasks.json`, self-reviews the plan against the spec, then calls `AskUserQuestion` with the two execution options.
5. User picks **Subagent-Driven**. Plan-writer invokes `subagent-driven-development`.
6. **subagent-driven-development**, as controller, ensures a worktree exists (delegates to `using-git-worktrees` if not), then for each task in dependency order:
   - Reads the task via `TaskGet`, parses the `json:metadata`.
   - Dispatches an implementer subagent with the implementer-prompt template, fully self-contained context, in the worktree directory.
   - The implementer follows TDD internally (`test-driven-development` skill), writes the failing test, watches it fail, writes minimal code, watches it pass, commits, self-reviews, returns DONE.
   - Controller dispatches the spec-compliance reviewer subagent. Reviewer reads code (not the implementer's report), compares to spec line-by-line, returns ✅ or ❌ with specifics.
   - If ❌: implementer fixes, spec reviewer re-reviews, loop until ✅.
   - Controller dispatches the code-quality reviewer subagent using the `code-reviewer` agent template. Returns Critical/Important/Minor issues.
   - Implementer fixes Critical and Important. Loop until approved.
   - Controller marks task `completed`, syncs `.tasks.json`.
7. After all tasks complete, controller dispatches a final code-reviewer over the entire implementation.
8. Controller invokes `finishing-a-development-branch`. That skill verifies tests pass, presents the 4 options. User picks "Push and create PR." Skill executes `git push -u origin <branch>` and `gh pr create --title ... --body ...`.
9. End.

If anything goes wrong at any step — a test fails, the implementer gets stuck, the reviewer finds critical issues — `systematic-debugging` is invoked by whichever agent encountered the failure, walking the four phases before any fix is attempted. Before any "done" claim is made anywhere in the pipeline, `verification-before-completion` requires running the actual verification command and reading its output.

---

## 13. Summary

**Superpowers is process-as-code.** It encodes a particular software-engineering workflow — TDD-driven, design-first, root-cause-respecting, evidence-before-claims, two-stage-reviewed — as a set of skill documents that an LLM coding agent is forced (by SessionStart-hook injection of a meta-skill) to consult before responding. The skills compose into a pipeline from idea → design → plan → tasks → implementation → review → merge/PR.

The `superpowers-extended-cc` fork specifically adds Claude Code-native task integration: real harness tasks with dependency enforcement, a metadata-embedding trick to make those tasks self-describing across subagent dispatch, sidecar `.tasks.json` for cross-session resume, and two optional hooks (a pre-commit task-completion gate and a stop-deflection guard) that catch the two most common ways an agent can sneak past the discipline.

The whole thing is markdown plus a handful of bash hooks. There is no runtime, no daemon, no compiled component. The force comes entirely from skill text engineered against observed rationalizations, plus harness-level enforcement at the two points where text isn't enough.

# Spec: <task name>

> Status: draft | dispatched | satisfied | superseded
> Scope: <inferred or explicit>
> Owner: <who is on the hook>

## Goal
One sentence: what this spec produces.

## Scope
`<repo>/<module>` or `global`. Auto-inferred by default; override only if the inference is wrong.

## Boundaries
- **In:** what is included
- **Out:** what is explicitly excluded

## Dependencies
- Other Spec ids this depends on, or "none".

## Estimated Complexity
S | M | L  (with one sentence of why).

## Acceptance Criteria
A JSON list, one entry per criterion. Each must pass `validate_criterion`:

```json
[
  {
    "text": "function returns slug of input string",
    "verify": "pytest tests/test_slugify.py::test_basic -v passes"
  },
  {
    "text": "non-ASCII characters are transliterated, not stripped silently",
    "verify": "pytest tests/test_slugify.py::test_unicode -v passes"
  }
]
```

## Known Risks / Open Questions
- Bulleted, or "none".

## Required Reads
JSON list of node ids the builder should load before starting:

```json
["module:slugify", "decision:str-handling-policy"]
```

## Feedback Loop
How will we know if this is working in real use, and what's the path from misbehavior back to a fix? Must name an observable signal AND a fix path. Validated by `validate_feedback_loop`.

---

## Example 1 - Trivial task: `slugify(s)`

### Goal
Implement a `slugify(s: str) -> str` utility in `src/util/text.py`.

### Scope
`src/util`

### Boundaries
- **In:** ASCII lowercasing, whitespace-to-hyphen, transliteration of accented Latin letters.
- **Out:** non-Latin scripts (CJK), emoji handling, language-specific rules.

### Dependencies
none

### Estimated Complexity
S - one function, one test file, no I/O.

### Acceptance Criteria
```json
[
  {"text": "slugify('Hello World') == 'hello-world'", "verify": "pytest tests/test_slugify.py::test_basic -v passes"},
  {"text": "slugify('Creme Brulee') == 'creme-brulee'", "verify": "pytest tests/test_slugify.py::test_accents -v passes"},
  {"text": "slugify('a  b') == 'a-b' (collapses whitespace)", "verify": "pytest tests/test_slugify.py::test_whitespace -v passes"}
]
```

### Known Risks / Open Questions
- What's the policy for CJK input? Decision: pass-through unchanged, document explicitly.

### Required Reads
none

### Feedback Loop
If a user files a bug that a slug round-trips badly through URL handling, we will write a regression test reproducing it and open a PR fixing it. Pattern-finder watches for repeat slugify bugs.

---

## Example 2 - Real feature: `/agentic:status` command

### Goal
Add a slash command that prints a one-screen summary of the current project's graph state: open Specs, open Findings by severity, recent Retros.

### Scope
`commands/` + `mcp-server/src/agentic_mcp`

### Boundaries
- **In:** read-only graph queries; printed via `query_graph`.
- **Out:** any mutation; any external HTTP; cross-project views.

### Dependencies
- Spec for Phase 0 graph queries (`query_graph` must exist).

### Estimated Complexity
M - needs a command file, formatting code, integration tests.

### Acceptance Criteria
```json
[
  {"text": "command file commands/status.md exists with frontmatter", "verify": "pytest tests/test_command_files.py::test_status_present -v passes"},
  {"text": "running the command in a sample project prints the open Spec count", "verify": "pytest tests/test_status_command.py::test_open_spec_count -v passes"},
  {"text": "running with an empty graph prints 'no project state yet'", "verify": "pytest tests/test_status_command.py::test_empty -v passes"}
]
```

### Known Risks / Open Questions
- Should it call out stale nodes (>N days untouched)? Defer to Phase 2 orchestrator.

### Required Reads
```json
["module:queries", "skill:router"]
```

### Feedback Loop
If users open Findings stating "status output is misleading", we will write a regression test against the misleading case and fix in a PR. Pattern-finder flags repeat misleading-output bugs.

---

## Example 3 - Bug fix: sqlite-vec fails on system Python

### Goal
Investigate and fix `vec_version()` returning NULL when the user runs the server with a Python that doesn't support `enable_load_extension`.

### Scope
`mcp-server/src/agentic_mcp/db.py`

### Boundaries
- **In:** detect the missing capability at startup; surface a clear error.
- **Out:** bundling our own Python build; switching SQLite drivers.

### Dependencies
none

### Estimated Complexity
S - diagnostic guard + clearer error message.

### Acceptance Criteria
```json
[
  {"text": "init_db raises RuntimeError naming 'enable_load_extension' if missing", "verify": "pytest tests/test_db.py::test_missing_load_extension_capability -v passes"},
  {"text": "error message includes a link to install instructions", "verify": "pytest tests/test_db.py::test_error_message_helpful -v passes"}
]
```

### Known Risks / Open Questions
- Anaconda Python is the most common culprit; do we want to recommend pyenv or python.org installer? Decision: link to python.org, mention Anaconda as known-bad.

### Required Reads
```json
["module:db", "retro:r-2026-04-12-anaconda-sqlite"]
```

### Feedback Loop
If a user files an install issue mentioning vec_version, we will check whether the guard fired correctly; if not, we will tighten the guard and write a regression test. The retro this fix produces is itself part of the loop.

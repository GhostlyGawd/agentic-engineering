---
description: Turn a rough intent into a Spec that passes validate_spec, via the spec-writer subagent (Socratic pass + inline validation + retry cap).
argument-hint: "<rough intent, or path to a notes file>"
---

Steps for Claude to execute:

1. Treat `$1` as the rough intent. If it is a path to an existing file, read its
   contents and use that as the intent.
2. Dispatch the `spec-writer` subagent (Task tool), handing it the intent. The
   spec-writer reads `skills/spec-writing/SKILL.md`, runs the Socratic pass,
   calls `validate_spec` inline, and loops until it passes (capped at 5
   attempts).
3. If the spec-writer created a Spec: report the new Spec id to the user, and
   remind them it is not dispatched yet - `/agentic:dispatch <id>` locks the
   criteria and starts the build.
4. If the spec-writer hit its retry cap and escalated: show its final draft and
   the remaining `validate_spec` reasons verbatim, so the user can resolve the
   ambiguity (usually an intent question, not a wording fix). Do NOT create the
   Spec node yourself to "get past" the gate.

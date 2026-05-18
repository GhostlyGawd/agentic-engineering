# Skill invocation policy for this repo

This repo is a study of the `superpowers-extended-cc` plugin. Only skills and commands shipped by that plugin may be auto-invoked here.

## Allow-list (auto-invocation permitted)

All skills from `superpowers-extended-cc`:
- brainstorming
- dispatching-parallel-agents
- executing-plans
- finishing-a-development-branch
- receiving-code-review
- requesting-code-review
- subagent-driven-development
- systematic-debugging
- test-driven-development
- using-git-worktrees
- using-superpowers
- verification-before-completion
- writing-plans
- writing-skills

All commands from `superpowers-extended-cc`:
- /brainstorm
- /execute-plan
- /write-plan

## Default-deny rule

Do NOT auto-invoke any other skill in this repo, even if its trigger description matches the user's request. This includes:
- User-global skills under `~/.claude/skills/` (e.g. `amazon-ads-*`, `meta-map`, `plan-interviewer`, `pm`, `worker`, `reviewer`, `notion-organizer`, `project-portfolio-audit`).
- User-global commands under `~/.claude/commands/` (e.g. `/board`, `/swarm`, `/mine-transcripts`, `/loop`, `/schedule`, `/simplify`, etc.).
- Built-in Claude Code skills (`init`, `review`, `security-review`).
- Skills from any other plugin.

## Explicit user invocation always wins

If the user types `/skill-name` or `/command-name` directly, run it regardless of the allow-list — that is explicit intent, not auto-invocation. If a denied skill seems obviously right for the request, mention it and ask before invoking; do not silently fire it.

## Ignore List

Do not read norns-loop-review unless EXPLICITLY requested by the user. You should completely ignore that folder and it's files.
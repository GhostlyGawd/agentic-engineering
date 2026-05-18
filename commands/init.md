---
description: Initialize a .agentic/ directory at the current project root with chosen scope mode.
argument-hint: "[scope-mode: isolated | workspace | personal]"
---

Run the `agentic-mcp-init` CLI to scaffold the project state directory.

If the user passed an argument as `$1`, use it as the scope mode. Otherwise use `isolated`.

Steps:

1. Use the Bash tool to run: `agentic-mcp-init --root . --scope-mode {{$1 or "isolated"}}`
2. Confirm with the user that `.agentic/` was created and report:
   - Database path
   - Scope mode
   - That they can now write Specs using `templates/spec.md`

If the command fails because `agentic-mcp` is not on PATH, instruct the user to
`pip install -e mcp-server` inside the plugin's venv first.

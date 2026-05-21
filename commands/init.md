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
3. Tell the user that a `.mcp.json` was written at the project root registering
   the `agentic-graph` MCP server, and that they must **restart Claude Code (or
   reconnect MCP)** for it to connect. Verify with:
   `claude mcp list` -> `agentic-graph ... - Connected`.

Note: `agentic-mcp-init` runs from the plugin's venv; the `.mcp.json` it writes
points Claude Code at that same venv interpreter, so no global PATH setup is
required. If `agentic-mcp-init` itself is not found, run it via the venv:
`mcp-server\.venv\Scripts\python.exe -m agentic_mcp.init_project --root .`.

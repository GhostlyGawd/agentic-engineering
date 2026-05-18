---
description: List installed Claude Code plugins, surface known overlaps with the agentic-engineering plugin, and record the user's coexistence preference. Informational only; never modifies another plugin.
---

This command does **not** disable any other plugin. It surfaces information and
records the user's stated preference.

Steps for Claude to execute:

1. Use the Bash tool to run:

   ```powershell
   python -c "from agentic_mcp import conflicts; import json; print(conflicts.render(conflicts.detect(plugins_dir=r'$env:USERPROFILE\.claude\plugins')))"
   ```

2. Show the output to the user.
3. If overlaps were found, ask the user which option they prefer (use AskUserQuestion).
4. Once they pick, run:

   ```powershell
   python -c "from agentic_mcp import conflicts; conflicts.record_preference(project_root='.', chosen='<their choice slug>')"
   ```

5. Confirm to the user that the preference has been recorded in
   `.agentic/compatibility.json` and that no other plugin's files were touched.

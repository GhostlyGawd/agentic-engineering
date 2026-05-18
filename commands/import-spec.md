---
description: Import an external plan (text or file) as a validated Spec node in the graph. Rejects with reasons if it does not pass the falsifiability and feedback-loop gates.
argument-hint: "<path-to-file or paste text>"
---

Steps for Claude to execute:

1. If `$1` is a path to an existing file: read its contents. Otherwise treat `$1`
   as inline markdown.
2. Run:

   ```powershell
   python -c @"
import sys, json
from agentic_mcp import db, import_spec
text = sys.stdin.read()
conn = db.connect('.agentic/graph.db')
sid, reasons = import_spec.from_markdown(conn, text, owner='user')
print(json.dumps({'id': sid, 'reasons': reasons}))
"@ < <input file or string>
   ```

3. If `id` came back non-null: report the new Spec id to the user.
4. If `id` is null: show the reasons list verbatim so the user knows what to fix
   in their external plan before re-importing.

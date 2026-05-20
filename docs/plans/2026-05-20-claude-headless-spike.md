# Claude Headless CLI Spike Notes

**Date:** 2026-05-20
**Status:** Complete - facts confirmed, no unknowns remaining

## Working Command

```powershell
claude -p "<prompt>" --output-format json
```

## Confirmed Facts

| Fact | Value |
|------|-------|
| Exit code | 0 (success) |
| Auth mechanism | Claude Max subscription (OAuth) - NO API key required |
| claude version | 2.1.145 |
| Result field | Top-level JSON field `result` (a string) |
| Permission flag for headless workers | `--permission-mode bypassPermissions` |

## JSON Shape

The `--output-format json` payload carries the assistant's final text in the
top-level `result` field:

```json
{
  "result": "<assistant text here>",
  ...
}
```

## Impact on llm_harness.py

The `result_text` function's FIRST branch `payload["result"]` is correct as
written. No change needed. The `payload.get("text")` branch is a fallback for
future CLI drift only.

## Headless Worker Flag

For sessions that need non-interactive file edits and bash execution:

```
--permission-mode bypassPermissions
```

This flag is NOT needed for the smoke test (read-only prompt/response), but is
required for the full e2e exit-gate test (Task 16) where the builder agent
writes files.

---
description: Surface recurring patterns in the graph. Lists open Pattern nodes awaiting triage, then runs one pattern-finding tick over the Finding/Bug/Retro stream (structural pre-cluster -> pattern-finder confirm -> mint with a derived-from evidence trail). On-demand companion to the scheduled tick.
argument-hint: "[scope]"
---

You are surfacing recurring patterns. Pattern STATE lives in the graph; this
command drives one pass and reports.

## Step 1 - Show open patterns awaiting triage

Call `query_graph(type="Pattern", status="open")`. For each, print its id,
summary, and the count of its `derived-from` evidence. These are candidates a
human (or the architectural-review layer) should triage with `triage_pattern`
(disposition `confirmed` or `dismissed`).

## Step 2 - Run one pattern-finding tick

Run the single-tick finder over the current graph. If you were given a scope
argument (`$1`), pass it; otherwise OMIT `--scope` entirely to scan all scopes
(do not pass an empty `--scope`, which would filter to the empty-string scope and
match nothing):

```
python -m agentic_mcp.patterns --once                  # all scopes
python -m agentic_mcp.patterns --once --scope <scope>  # one scope
```

It groups active Finding/Bug/Retro nodes by structural signal (shared parent_id,
subtype, tag/file, or failed_layer), and for each group of >= 3 it asks the
pattern-finder agent to confirm or reject. Confirmed groups become open Pattern
nodes (linked `derived-from` their evidence); declined groups get a system
dismissed-tombstone so they are not re-evaluated next run.

## Step 3 - Report

Print the tick's JSON summary (`minted`, `dismissed`, `considered`, `errors`).
Newly `minted` Patterns are `open` - surface them for triage via `triage_pattern`.

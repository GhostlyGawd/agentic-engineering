---
name: spec-writing
description: How to write a Spec that passes the falsifiability and feedback-loop gates. Includes a Socratic intent-clarification pass to run before locking the spec.
---

# Spec Writing (Phase 0)

A Spec is the contract between intent and build. It must answer two questions
mechanically:

1. **How will we know each criterion is satisfied?** Not "looks right" - a runnable
   command, a type/lint check, or a named runtime observation.
2. **How will we know if the resulting artifact is working in real use, and how
   would a failure get fixed?** This is the feedback loop. Without it, the artifact
   ships blind.

Both gates are enforced by `validate_spec` (MCP tool). The orchestrator refuses
to dispatch a Spec that doesn't pass.

## Workflow

1. Start from `templates/spec.md`. Copy the structure; fill in each section.
2. Run the **Socratic pass** below. Update the spec based on what surfaces.
3. Call `validate_spec` with the criteria_json and feedback_loop.
4. If it returns reasons, fix the spec - don't argue with the validator. The
   validator is mechanical; if its complaints feel unfair, the criterion is
   probably under-specified.
5. Create the Spec node via `create_node(type='Spec', ...)`.
6. Link it to its Goal/Epic via `link_nodes(spec_id, goal_id, 'implements')`.

## Socratic intent-clarification pass

Before locking the spec, ask the user (or yourself, if no user is present) these
questions. The aim is to surface assumptions the spec is currently silent about.

1. **What changes for the user once this exists?** Name the observable difference.
2. **What is explicitly out of scope?** Anything you don't say "no" to becomes
   implicitly in scope.
3. **What happens if this is wrong?** Worst-case behavior shapes the criteria.
4. **Who else cares?** Stakeholders you haven't named will produce surprise
   requirements mid-build.
5. **What is the smallest possible version that's still useful?** If you can't
   answer, the spec is too big.
6. **What would falsify "this is done"?** Concretely. If the answer is "I'll know
   it when I see it", the criteria aren't ready.
7. **If this silently breaks 6 months from now, how do we find out?** That is the
   feedback loop.

If any answer is "I don't know yet", that becomes an entry in **Known Risks /
Open Questions**, not a hidden assumption in the body.

## Common rejections from `validate_spec`

| Rejection                                        | Fix                                                                                                  |
|--------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `verify field contains hand-wavy language`       | "works correctly" / "handled appropriately" / "tbd" are not verification. Name a command or signal.   |
| `verify must name a runnable command or signal`  | Prefix with `pytest`, `mypy`, `npm test`, etc. - or describe a runtime metric / log line / alert.    |
| `feedback_loop must name an observable signal`   | Add the signal: a user report, CI failure, metric, log line, dashboard view.                          |
| `feedback_loop must name a fix path`             | Say what we do when the signal fires: "open a bug", "file a retro", "PR a fix", "rollback".          |
| `spec has no acceptance criteria`                | Empty criteria_json. Even trivial tasks need at least one falsifiable criterion.                      |

## Examples

See `templates/spec.md`, Examples 1-3, for: a trivial utility, a real feature,
and a bug fix. All three pass `validate_spec`.

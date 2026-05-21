---
description: Validate a Spec, lock its criteria (dispatched_at), and kick the builder for iteration 1. After this point the spec's criteria are immutable - changes require a superseding Spec.
argument-hint: "<spec_id>"
---

Steps for Claude to execute:

1. Resolve the spec id from `$1`. Call `get_node(id=$1)`; if it is not a `Spec`,
   stop and tell the user.
2. Re-run the gate before locking. Call
   `validate_spec(criteria_json=<spec.criteria_json>, feedback_loop=<spec.feedback_loop>)`.
   If it returns `ok: false`, show the reasons verbatim and STOP - do not
   dispatch a spec that fails its own gate. Send the user to the spec-writer.
3. Lock the spec: call `dispatch_spec(spec_id=$1)`. This stamps `dispatched_at`.
   From now on the criteria are immutable - any later attempt to edit them is
   rejected and the user must create a new Spec with a `supersedes` relation to
   this one.
4. Kick iteration 1: dispatch the `builder` subagent (Task tool) against this
   spec id. The builder implements, self-verifies, and records what it did to
   the graph.
5. Report the dispatched spec id and the builder's outcome to the user. The
   review loop is a separate step: `/agentic:review-pr`.

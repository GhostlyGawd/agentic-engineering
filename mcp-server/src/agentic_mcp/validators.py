"""Falsifiability + feedback-loop validators."""
from __future__ import annotations

import json
import re
import sqlite3

_HANDWAVE_PATTERNS = [
    r"\btbd\b",
    r"\btodo\b",
    r"see above",
    r"works? correctly",
    r"appropriately",
    r"\bhandled\b",
    r"as needed",
    r"if necessary",
]

_VERIFY_COMMAND_PREFIXES = (
    "pytest", "npm ", "cargo ", "go test", "./", "python ", "python -",
    "bash ", "pwsh ", "powershell", "mypy", "ruff", "eslint", "tsc",
    "make ", "just ", "tox ",
)

_RUNTIME_SIGNALS = (
    "logs show", "metric", "telemetry", "log line", "alert fires",
    "dashboard shows", "trace", "p95", "p99", "error rate", "5xx",
)

_FEEDBACK_SIGNALS = (
    "user reports", "user report", "users report", "users reports",
    "ci fails", "ci passes", "metric", "telemetry",
    "test", "alert", "log", "monitor", "dashboard", "regression test",
    "review finds", "audit",
)

_FEEDBACK_FIX_PATHS = (
    "file a bug", "open issue", "open a bug", "open a ticket", "retro",
    "pr ", "patch", "fix", "revert", "rollback", "roll back",
    "hotfix", "amend", "write a", "log a",
)


def _has_handwave(s: str) -> bool:
    lower = s.lower()
    return any(re.search(p, lower) for p in _HANDWAVE_PATTERNS)


def validate_criterion(text: str, verify: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not verify or not verify.strip():
        reasons.append("verify field is empty")
        return False, reasons
    if len(verify.strip()) < 6:
        reasons.append("verify field is too short to describe a real check")
    if _has_handwave(verify):
        reasons.append(f"verify field contains hand-wavy language: {verify!r}")
    lower = verify.lower().strip()
    looks_runnable = any(lower.startswith(p) for p in _VERIFY_COMMAND_PREFIXES)
    looks_runtime = any(s in lower for s in _RUNTIME_SIGNALS)
    if not (looks_runnable or looks_runtime):
        reasons.append(
            "verify must name a runnable command, type/lint check, or runtime observation"
        )
    return (len(reasons) == 0), reasons


def validate_feedback_loop(text: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not text or not text.strip():
        reasons.append("feedback_loop is empty")
        return False, reasons
    if len(text.strip()) < 20:
        reasons.append("feedback_loop is too short to describe signal + fix path")
    if _has_handwave(text):
        reasons.append(f"feedback_loop contains hand-wavy language: {text!r}")
    lower = text.lower()
    has_signal = any(s in lower for s in _FEEDBACK_SIGNALS)
    has_fix = any(s in lower for s in _FEEDBACK_FIX_PATHS)
    if not has_signal:
        reasons.append("feedback_loop must name an observable signal")
    if not has_fix:
        reasons.append("feedback_loop must name a fix path")
    return (len(reasons) == 0), reasons


def validate_dispatched_immutable(
    conn: sqlite3.Connection, spec_id: str, new_criteria: list[dict]
) -> tuple[bool, list[str]]:
    """Reject criteria changes on an already-dispatched spec.

    Compares (text, verify, order, count) of new_criteria against the stored
    criteria. If the spec is not dispatched, always passes.
    """
    from . import nodes
    spec = nodes.get_node(conn, spec_id)
    if spec is None or spec["type"] != "Spec":
        return False, [f"not a Spec node: {spec_id}"]
    if not spec.get("dispatched_at"):
        return True, []
    stored = json.loads(spec["criteria_json"])
    stored_sig = [(c.get("text"), c.get("verify")) for c in stored]
    new_sig = [(c.get("text"), c.get("verify")) for c in new_criteria]
    if stored_sig != new_sig:
        return False, [
            f"spec {spec_id} was dispatched at {spec['dispatched_at']}; criteria "
            "cannot change after dispatch. Create a new Spec with a 'supersedes' "
            "relation to this one instead."
        ]
    return True, []


def validate_spec(spec: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    try:
        criteria = json.loads(spec.get("criteria_json") or "[]")
    except (ValueError, TypeError) as e:
        return False, [f"criteria_json not valid JSON: {e}"]
    if not criteria:
        reasons.append("spec has no acceptance criteria")
    for i, c in enumerate(criteria):
        ok, why = validate_criterion(c.get("text", ""), c.get("verify", ""))
        if not ok:
            reasons.extend(f"criterion[{i}]: {r}" for r in why)
    ok_fb, why_fb = validate_feedback_loop(spec.get("feedback_loop", ""))
    if not ok_fb:
        reasons.extend(why_fb)
    return (len(reasons) == 0), reasons

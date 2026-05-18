"""Bridge: parse an external markdown plan into a validated Spec node."""
from __future__ import annotations

import json
import re
import sqlite3

from . import nodes, validators

_CRIT_RE = re.compile(
    r"###\s*Acceptance Criteria\s*```json\s*(\[.*?\])\s*```", re.S | re.I
)
_FB_RE = re.compile(r"###\s*Feedback Loop\s*\n(.+?)(?:\n#|\Z)", re.S | re.I)


def from_markdown(
    conn: sqlite3.Connection, text: str, owner: str
) -> tuple[str | None, list[str]]:
    crit_match = _CRIT_RE.search(text)
    fb_match = _FB_RE.search(text)
    if not crit_match:
        return None, ["could not find an Acceptance Criteria JSON block"]
    if not fb_match:
        return None, ["could not find a Feedback Loop section"]
    criteria_json = crit_match.group(1).strip()
    feedback_loop = fb_match.group(1).strip()
    # Normalize criteria: ensure each entry has satisfied field.
    try:
        parsed = json.loads(criteria_json)
    except ValueError as e:
        return None, [f"criteria_json not valid JSON: {e}"]
    for c in parsed:
        c.setdefault("satisfied", False)
    criteria_json = json.dumps(parsed)

    spec_dict = {"criteria_json": criteria_json, "feedback_loop": feedback_loop}
    ok, reasons = validators.validate_spec(spec_dict)
    if not ok:
        return None, reasons

    sid = nodes.create_node(
        conn, "Spec", status="draft", owner=owner, body=text,
        criteria_json=criteria_json, feedback_loop=feedback_loop,
    )
    return sid, []

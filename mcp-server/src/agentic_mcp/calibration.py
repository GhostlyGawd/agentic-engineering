"""Per-role confidence calibration (trust-weighting).

Each role accrues hit/miss observations; score is a Laplace-smoothed hit-rate.
When the score crosses the floor the role is marked distrusted (the orchestrator
then requires a second reviewer and discounts that role's Criticals); sustained
recovery above the ceiling clears it. adjust_trust reports whether the flag
actually changed - a flip is the "calibration adjustment fired" the exit gate
checks for.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

FLOOR = 0.4
CEILING = 0.7
_SMOOTHING = 1  # Laplace add-one


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _score(hits: int, observations: int) -> float:
    return (hits + _SMOOTHING) / (observations + 2 * _SMOOTHING)


def _ensure_row(conn: sqlite3.Connection, role: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO calibration(role, score) VALUES (?, 0.5)", (role,)
    )


def record_outcome(conn: sqlite3.Connection, role: str, hit: bool) -> None:
    _ensure_row(conn, role)
    col = "hits" if hit else "misses"
    conn.execute(
        f"UPDATE calibration SET observations = observations + 1, {col} = {col} + 1 "
        "WHERE role=?",
        (role,),
    )
    row = conn.execute(
        "SELECT hits, observations FROM calibration WHERE role=?", (role,)
    ).fetchone()
    conn.execute(
        "UPDATE calibration SET score=? WHERE role=?",
        (_score(row[0], row[1]), role),
    )
    conn.commit()


def get_calibration(conn: sqlite3.Connection, role: str) -> dict:
    row = conn.execute(
        "SELECT role, observations, hits, misses, score, last_adjusted_at, distrusted "
        "FROM calibration WHERE role=?",
        (role,),
    ).fetchone()
    if row is None:
        return {"role": role, "observations": 0, "hits": 0, "misses": 0,
                "score": 0.5, "last_adjusted_at": None, "distrusted": 0}
    keys = ["role", "observations", "hits", "misses", "score", "last_adjusted_at", "distrusted"]
    return dict(zip(keys, row))


def adjust_trust(conn: sqlite3.Connection, role: str) -> dict:
    c = get_calibration(conn, role)
    current = c["distrusted"]
    target = current
    if c["score"] < FLOOR:
        target = 1
    elif c["score"] > CEILING:
        target = 0
    adjusted = target != current
    if adjusted:
        _ensure_row(conn, role)
        conn.execute(
            "UPDATE calibration SET distrusted=?, last_adjusted_at=? WHERE role=?",
            (target, _now(), role),
        )
        conn.commit()
    return {"adjusted": adjusted, "distrusted": target}

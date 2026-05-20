"""Stability check: detect contradiction-of-prior-approval (design sections 8, 12).

The instability signal is NOT 'a Critical on an unchanged file' (that punishes
legitimate late discovery). It is a Critical on a file whose git blob is
byte-identical between two iteration commits AND that the reviewer had
previously EXPLICITLY approved. We record a soft Pattern; we never suppress the
Critical (Phase 1 detects, Phase 4 calibration judges).
"""
from __future__ import annotations

import sqlite3
import subprocess

from . import nodes


def _blob_sha(repo: str, commit: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"],
        cwd=repo, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def detect_stability_contradiction(
    conn: sqlite3.Connection,
    repo: str,
    path: str,
    commit_before: str,
    commit_after: str,
    prior_approval: bool,
) -> str | None:
    """Return a Pattern id if a contradiction is detected, else None.

    prior_approval: did the reviewer explicitly approve this file in an earlier
    round (logged a Strength on it, or marked it clean)? Late discovery passes
    False here and is never a contradiction.
    """
    if not prior_approval:
        return None  # late discovery is legitimate, not instability
    before = _blob_sha(repo, commit_before, path)
    after = _blob_sha(repo, commit_after, path)
    if before is None or after is None or before != after:
        return None  # code changed (or path missing) -> legitimate re-review
    return nodes.create_node(
        conn, "Pattern", status="open", owner="system", severity="Suggested",
        body=(
            f"stability: {path} was flagged Critical on byte-identical blob "
            f"{after} ({commit_before[:8]}..{commit_after[:8]}) after a prior "
            "explicit approval. Calibration signal only; the Critical is still "
            "actioned. Phase 1 records, Phase 4 calibration judges."
        ),
        tags="stability,contradiction",
    )

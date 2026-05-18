"""Scope auto-inference for graph nodes.

Priority order:
  1. explicit
  2. parent_scope
  3. path mentions in body (longest common dir prefix)
  4. recent_files (longest common dir prefix)
  5. basename of cwd
  6. "global"
"""
from __future__ import annotations

import re
from os.path import commonpath
from pathlib import Path

_PATH_TOKEN = re.compile(r"[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+")


def _lcp_dir(paths: list[str]) -> str | None:
    if not paths:
        return None
    norm = [p.replace("\\", "/") for p in paths]
    try:
        cp = commonpath(norm).replace("\\", "/")
    except ValueError:
        return None
    # If the cp is a file (has an extension), drop the filename.
    if "." in cp.rsplit("/", 1)[-1]:
        cp = cp.rsplit("/", 1)[0] if "/" in cp else cp
    return cp or None


def infer_scope(
    body: str,
    *,
    explicit: str | None = None,
    parent_scope: str | None = None,
    cwd: Path | str | None = None,
    recent_files: list[str] | None = None,
) -> str:
    if explicit:
        return explicit
    if parent_scope:
        return parent_scope
    body_paths = _PATH_TOKEN.findall(body or "")
    body_scope = _lcp_dir(body_paths)
    if body_scope:
        return body_scope
    if recent_files:
        rf_scope = _lcp_dir(recent_files)
        if rf_scope:
            return rf_scope
    if cwd:
        return Path(cwd).name
    return "global"

"""Supervisor configuration: project registry + cadence interpretation.

Pure config logic. The registry (~/.agentic/registry.json) lists which projects
the supervisor daemon watches and at what cadence. This module does no I/O beyond
reading that one file and no process work. Distinct from registry.py (the
unrelated plugin known-overlap table).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

_CADENCE_RE = re.compile(r"^(\d+)([smhdw])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_ALIASES = {"hourly": 3600, "daily": 86400, "weekly": 604800}


def default_registry_path() -> Path:
    raw = os.environ.get("AGENTIC_REGISTRY_PATH")
    if raw:
        return Path(raw).resolve()
    return (Path.home() / ".agentic" / "registry.json").resolve()


def load_registry(path: str | Path) -> dict:
    """Return {"projects": [normalized...]}. Missing file -> empty. Malformed
    JSON or a non-list projects -> ValueError (a startup config error, fail loud)."""
    p = Path(path)
    if not p.exists():
        return {"projects": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise ValueError(f"malformed registry {p}: {e}") from e
    projects = data.get("projects", [])
    if not isinstance(projects, list):
        raise ValueError(f"registry {p}: 'projects' must be a list")
    return {"projects": [_normalize_project(x) for x in projects]}


def _normalize_project(raw: dict) -> dict:
    if not isinstance(raw, dict) or "path" not in raw:
        raise ValueError(f"registry project missing 'path': {raw!r}")
    return {
        "path": str(raw["path"]),
        "enabled": bool(raw.get("enabled", True)),
        "scope_mode": str(raw.get("scope_mode", "isolated")),
        "cadences": dict(raw.get("cadences", {})),
        "promotion_cap": int(raw.get("promotion_cap", 5)),
    }


def parse_cadence(text: str) -> int:
    """Cadence string -> seconds. Grammar: Ns/Nm/Nh/Nd/Nw, plus aliases."""
    if text in _ALIASES:
        return _ALIASES[text]
    m = _CADENCE_RE.match(text or "")
    if not m:
        raise ValueError(f"bad cadence: {text!r}")
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)]


def is_due(last_run: str | None, cadence: str, now: datetime) -> bool:
    """True if the tick has never run or enough time has elapsed since last_run."""
    if not last_run:
        return True
    last = datetime.fromisoformat(last_run)
    return (now - last).total_seconds() >= parse_cadence(cadence)

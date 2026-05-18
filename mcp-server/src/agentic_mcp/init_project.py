"""Initialize a .agentic/ directory at a given project root."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import db as db_mod

VALID_SCOPE_MODES = {"isolated", "workspace", "personal"}


def run(project_root: Path | str, scope_mode: str = "isolated") -> None:
    if scope_mode not in VALID_SCOPE_MODES:
        raise ValueError(
            f"invalid scope_mode: {scope_mode!r}. Valid: {sorted(VALID_SCOPE_MODES)}"
        )
    root = Path(project_root).resolve()
    agentic = root / ".agentic"
    (agentic / "specs").mkdir(parents=True, exist_ok=True)

    db_path = agentic / "graph.db"
    if not db_path.exists():
        db_mod.init_db(db_path)
    else:
        # Apply schema idempotently in case it has been extended.
        db_mod.init_db(db_path)

    cfg_path = agentic / "config.json"
    cfg = {
        "scope_mode": scope_mode,
        "initialized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    compat_path = agentic / "compatibility.json"
    if not compat_path.exists():
        compat_path.write_text("{}\n", encoding="utf-8")


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Initialize .agentic/ at a project root.")
    p.add_argument("--root", default=".", help="project root (default cwd)")
    p.add_argument("--scope-mode", default="isolated", choices=sorted(VALID_SCOPE_MODES))
    args = p.parse_args()
    run(args.root, args.scope_mode)
    print(f"agentic: initialized at {Path(args.root).resolve() / '.agentic'}")

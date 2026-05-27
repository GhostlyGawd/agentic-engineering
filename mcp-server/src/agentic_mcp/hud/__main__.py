"""agentic-hud entry point. Resolves launch context: started inside a project
(walk up to a .agentic dir) -> open that workspace; started bare -> overview."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import supervisor_config as cfg
from .app import AgenticHUD
from .daemon_client import DaemonClient
from .graph_source import GraphSource


def _find_project_root(start: Path):
    for d in [start, *start.parents]:
        if (d / ".agentic" / "graph.db").exists():
            return d
    return None


def _build_sources(registry: dict) -> dict:
    sources = {}
    for proj in registry.get("projects", []):
        db_path = Path(proj["path"]) / ".agentic" / "graph.db"
        try:
            sources[proj["path"]] = GraphSource(db_path)
        except FileNotFoundError:
            pass
    return sources


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="agentic-hud")
    parser.add_argument("--port", type=int, default=None,
                        help="supervisor control API port (default 8787 / env)")
    args = parser.parse_args(argv)

    registry = cfg.load_registry(cfg.default_registry_path())
    sources = _build_sources(registry)
    daemon = DaemonClient(port=args.port)

    root = _find_project_root(Path.cwd())
    if root is not None:
        path = str(root.as_posix())
        if path not in sources and (root / ".agentic" / "graph.db").exists():
            sources[path] = GraphSource(root / ".agentic" / "graph.db")
        app = AgenticHUD(registry=registry, daemon=daemon, sources=sources,
                         start="workspace", active_path=path)
    else:
        app = AgenticHUD(registry=registry, daemon=daemon, sources=sources,
                         start="overview")
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

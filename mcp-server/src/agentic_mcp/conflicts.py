"""Conflict detection and informational coexistence rendering."""
from __future__ import annotations

import json
from pathlib import Path

from .registry import KNOWN_OVERLAPS


def detect(plugins_dir: Path | str) -> list[dict]:
    plugins_dir = Path(plugins_dir)
    out: list[dict] = []
    if not plugins_dir.exists():
        return out
    for plugin_dir in sorted(plugins_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest = plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        pid = plugin_dir.name
        overlap = KNOWN_OVERLAPS.get(pid)
        out.append({
            "plugin_id": pid,
            "name": data.get("name", pid),
            "version": data.get("version", "?"),
            "overlap": overlap,
        })
    return out


def render(detections: list[dict]) -> str:
    lines: list[str] = []
    overlapping = [d for d in detections if d["overlap"] is not None]
    if not overlapping:
        return (
            "No known overlapping plugins detected. "
            "(Other installed plugins are listed as 'unknown' and you should "
            "review them yourself.)"
        )
    for d in overlapping:
        ov = d["overlap"]
        lines.append(f"Detected: {ov['display_name']} (installed, enabled)")
        lines.append("")
        lines.append(
            f"Overlapping skill categories: {', '.join(ov['categories'])}."
        )
        lines.append("")
        lines.append(ov["coexistence_note"])
        lines.append("")
        lines.append("Options:")
        for label, body in ov["options"]:
            lines.append(f"  - {label}")
            lines.append(f"    {body}")
        lines.append("")
        lines.append(
            "No automatic changes will be made. You decide. "
            "If you want to disable a plugin, run /plugin disable yourself."
        )
    return "\n".join(lines)


def record_preference(project_root: Path | str, chosen: str) -> None:
    compat = Path(project_root) / ".agentic" / "compatibility.json"
    data: dict = {}
    if compat.exists():
        try:
            data = json.loads(compat.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data["choice"] = chosen
    from datetime import datetime, timezone
    data["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    compat.write_text(json.dumps(data, indent=2), encoding="utf-8")

"""v1 known-overlap registry (PRD D-33)."""
from __future__ import annotations

KNOWN_OVERLAPS: dict[str, dict] = {
    "superpowers-extended-cc": {
        "display_name": "Superpowers",
        "categories": [
            "planning", "code-review", "TDD", "debugging", "audit", "brainstorming",
        ],
        "coexistence_note": (
            "Both plugins can coexist via Claude Code's namespacing. Our cycle "
            "uses embedded tactical guidance integrated with our graph."
        ),
        "options": [
            (
                "Use ours end-to-end (recommended)",
                "Full graph integration. To avoid double-firing on PRs, consider "
                "/plugin disable superpowers.",
            ),
            (
                "Use Superpowers for ad-hoc work, ours for tracked tasks",
                "Both stay enabled, just be aware of doubled token cost on "
                "overlapping triggers.",
            ),
            (
                "Use Superpowers' planning, ours for build/review",
                "Use /agentic:import-spec to bring their plan output into our "
                "graph as a falsifiability-validated Spec node.",
            ),
        ],
    },
}

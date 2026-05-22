import json
from pathlib import Path
import pytest
from agentic_mcp import conflicts, registry, init_project


def _fake_plugin(plugins_dir: Path, plugin_id: str, name: str, version: str) -> None:
    pdir = plugins_dir / plugin_id / ".claude-plugin"
    pdir.mkdir(parents=True)
    (pdir / "plugin.json").write_text(
        json.dumps({"name": name, "version": version}), encoding="utf-8"
    )


def test_registry_has_superpowers():
    r = registry.KNOWN_OVERLAPS
    assert "superpowers-extended-cc" in r
    assert "categories" in r["superpowers-extended-cc"]


def test_detect_finds_superpowers(tmp_path):
    plugins = tmp_path / "plugins"
    _fake_plugin(plugins, "superpowers-extended-cc", "superpowers", "1.0.0")
    _fake_plugin(plugins, "some-other", "other", "0.1")
    detections = conflicts.detect(plugins_dir=plugins)
    by_id = {d["plugin_id"]: d for d in detections}
    assert by_id["superpowers-extended-cc"]["overlap"] is not None
    assert by_id["some-other"]["overlap"] is None


def test_render_contains_template_phrases(tmp_path):
    plugins = tmp_path / "plugins"
    _fake_plugin(plugins, "superpowers-extended-cc", "superpowers", "1.0.0")
    detections = conflicts.detect(plugins_dir=plugins)
    text = conflicts.render(detections)
    assert "Detected" in text
    assert "superpowers" in text.lower()
    assert "namespacing" in text
    assert "import-spec" in text


def test_record_preference_writes_only_inside_agentic(tmp_path):
    init_project.run(project_root=tmp_path, scope_mode="isolated")
    conflicts.record_preference(project_root=tmp_path, chosen="use-ours")
    compat = json.loads((tmp_path / ".agentic" / "compatibility.json").read_text())
    assert compat["choice"] == "use-ours"
    # Confirm nothing else was created at project root, except the .mcp.json
    # that init now writes to register the agentic-graph MCP server.
    others = [p.name for p in tmp_path.iterdir() if p.name not in {".agentic", ".mcp.json"}]
    assert others == []

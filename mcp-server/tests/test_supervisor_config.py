import json
from datetime import datetime, timedelta, timezone

import pytest

from agentic_mcp import supervisor_config as cfg


def test_default_registry_path_env_override(tmp_path, monkeypatch):
    target = tmp_path / "reg.json"
    monkeypatch.setenv("AGENTIC_REGISTRY_PATH", str(target))
    assert cfg.default_registry_path() == target.resolve()


def test_load_registry_applies_defaults(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"projects": [{"path": "C:/proj"}]}), encoding="utf-8")
    reg = cfg.load_registry(p)
    proj = reg["projects"][0]
    assert proj["enabled"] is True
    assert proj["scope_mode"] == "isolated"
    assert proj["cadences"] == {}


def test_load_registry_missing_file_is_empty(tmp_path):
    reg = cfg.load_registry(tmp_path / "nope.json")
    assert reg == {"projects": []}


def test_load_registry_malformed_raises(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        cfg.load_registry(p)


def test_load_registry_non_list_projects_raises(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"projects": "x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        cfg.load_registry(p)


@pytest.mark.parametrize("text,seconds", [
    ("30s", 30), ("2m", 120), ("6h", 21600), ("1d", 86400),
    ("1w", 604800), ("hourly", 3600), ("daily", 86400), ("weekly", 604800),
])
def test_parse_cadence(text, seconds):
    assert cfg.parse_cadence(text) == seconds


@pytest.mark.parametrize("bad", ["", "5", "m", "10x", "-3m", "1.5h"])
def test_parse_cadence_bad_raises(bad):
    with pytest.raises(ValueError):
        cfg.parse_cadence(bad)


def test_is_due_never_run():
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    assert cfg.is_due(None, "2m", now) is True


def test_is_due_elapsed():
    now = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    last = (now - timedelta(minutes=3)).isoformat()
    assert cfg.is_due(last, "2m", now) is True


def test_is_due_not_yet():
    now = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    last = (now - timedelta(seconds=30)).isoformat()
    assert cfg.is_due(last, "2m", now) is False

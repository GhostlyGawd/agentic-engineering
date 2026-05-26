import sys


def test_importing_agentic_mcp_does_not_import_textual():
    # Drop any pre-imported textual so the assertion is meaningful.
    for mod in [m for m in sys.modules if m == "textual" or m.startswith("textual.")]:
        del sys.modules[mod]
    import agentic_mcp  # noqa: F401
    import agentic_mcp.hud  # noqa: F401  -- package marker, still no textual
    assert "textual" not in sys.modules


def test_hud_extra_and_script_declared():
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert "hud" in data["project"]["optional-dependencies"]
    assert any("textual" in dep for dep in data["project"]["optional-dependencies"]["hud"])
    assert data["project"]["scripts"]["agentic-hud"] == "agentic_mcp.hud.__main__:main"

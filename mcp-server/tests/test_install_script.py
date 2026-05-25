from pathlib import Path


def _script() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "install-supervisor.ps1"


def test_install_script_exists():
    assert _script().exists()


def test_install_script_is_ascii():
    raw = _script().read_bytes()
    assert all(b < 128 for b in raw), "install-supervisor.ps1 must be ASCII-only"


def test_install_script_has_print_switch_and_task_name():
    text = _script().read_text(encoding="utf-8")
    assert "[switch]$Print" in text
    assert "AgenticSupervisor" in text
    assert "agentic-supervisor" in text

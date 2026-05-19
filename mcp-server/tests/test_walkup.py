import json
import subprocess
import sys
from pathlib import Path
import pytest

# Phase 0 is Windows-only. Tests that subprocess-invoke `powershell` are skipped
# on other platforms. A portable POSIX hook is Phase 1+ work.
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Phase 0 SessionStart hook is PowerShell-only (Windows)",
)

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "session-start.ps1"


def _run_hook(cwd: Path) -> tuple[int, str]:
    res = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HOOK)],
        cwd=cwd, capture_output=True, text=True,
    )
    return res.returncode, res.stdout


@pytest.fixture
def scaffolded(tmp_path):
    """Build a directory tree we can drop .agentic/ markers into."""
    (tmp_path / "ws" / "repo-a" / "src").mkdir(parents=True)
    (tmp_path / "ws" / "repo-b").mkdir(parents=True)
    return tmp_path


def test_no_agentic_anywhere_is_silent(scaffolded):
    code, out = _run_hook(scaffolded / "ws" / "repo-a" / "src")
    assert code == 0
    assert out.strip() == ""


def test_agentic_at_cwd_is_found(scaffolded):
    target = scaffolded / "ws" / "repo-a"
    (target / ".agentic").mkdir()
    code, out = _run_hook(target)
    assert code == 0
    payload = json.loads(out)
    assert "Agentic Engineering System is active" in payload["additionalContext"]
    assert str(target) in payload["additionalContext"]


def test_agentic_at_parent_is_found(scaffolded):
    target = scaffolded / "ws" / "repo-a"
    (target / ".agentic").mkdir()
    deep = target / "src"
    code, out = _run_hook(deep)
    assert code == 0
    payload = json.loads(out)
    assert str(target) in payload["additionalContext"]


def test_closest_agentic_wins(scaffolded):
    grandparent = scaffolded / "ws"
    closer = scaffolded / "ws" / "repo-a"
    (grandparent / ".agentic").mkdir()
    (closer / ".agentic").mkdir()
    code, out = _run_hook(closer / "src")
    assert code == 0
    payload = json.loads(out)
    assert str(closer) in payload["additionalContext"]
    assert str(grandparent) not in payload["additionalContext"].replace(str(closer), "")


def test_graph_stats_rendered_when_db_exists(scaffolded):
    """Regression for Phase 0 dogfood bug F-8adec081: when graph.db exists with
    real rows, the hook must render the integer counts, not empty strings.
    The Phase 0 walkup tests only created empty .agentic/ dirs, so the
    Read-GraphStats Python invocation was never exercised; PSNativeCommandArgument
    Passing strips embedded quotes from `python -c <script>` and the SQL
    SyntaxError silently fell to the catch block."""
    from agentic_mcp import db as db_mod, findings, init_project, nodes

    target = scaffolded / "ws" / "repo-a"
    init_project.run(project_root=target, scope_mode="isolated")

    # Seed: 1 open dispatched Spec + 2 open Critical Findings.
    conn = db_mod.connect(target / ".agentic" / "graph.db")
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="t", body="seed",
        criteria_json=json.dumps([
            {"text": "x", "verify": "pytest x.py -v", "satisfied": False},
        ]),
        feedback_loop=(
            "If users report breakage, file a bug and write a retro."
        ),
    )
    findings.log_finding(conn, spec_id, "Critical", body="seed crit 1")
    findings.log_finding(conn, spec_id, "Critical", body="seed crit 2")
    conn.close()

    code, out = _run_hook(target)
    assert code == 0
    payload = json.loads(out)
    ctx = payload["additionalContext"]
    assert "Open specs: 1" in ctx, f"expected 'Open specs: 1' in:\n{ctx}"
    assert "Open critical findings: 2" in ctx, (
        f"expected 'Open critical findings: 2' in:\n{ctx}"
    )

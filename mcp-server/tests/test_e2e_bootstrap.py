"""Phase 0 exit-gate test: full Spec -> build -> spec-check -> Finding flow."""
import json
import subprocess
import sys
from pathlib import Path

from agentic_mcp import db, findings, init_project, nodes, validators


SLUGIFY_CODE = '''
import re
import unicodedata


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s
'''


SLUGIFY_TEST = '''
from slugify_mod import slugify


def test_basic():
    assert slugify("Hello World") == "hello-world"


def test_accents():
    assert slugify("Creme Brulee") == "creme-brulee"


def test_whitespace():
    assert slugify("a  b") == "a-b"
'''


def test_phase_0_end_to_end(tmp_path):
    project = tmp_path / "scratch-project"
    project.mkdir()

    # 1. Initialize project state.
    init_project.run(project_root=project, scope_mode="isolated")
    db_path = project / ".agentic" / "graph.db"

    conn = db.connect(db_path)

    # 2. Write the artifact + test files (simulating the builder's output).
    (project / "slugify_mod.py").write_text(SLUGIFY_CODE)
    (project / "test_slugify.py").write_text(SLUGIFY_TEST)

    # 3. Create Goal + Spec nodes.
    goal_id = nodes.create_node(
        conn, "Goal", status="active", owner="bootstrap", body="ship slugify"
    )
    crit = [
        {"text": "basic ascii", "verify": "pytest test_slugify.py::test_basic -v"},
        {"text": "accents transliterated", "verify": "pytest test_slugify.py::test_accents -v"},
        {"text": "whitespace collapsed", "verify": "pytest test_slugify.py::test_whitespace -v"},
    ]
    spec_id = nodes.create_node(
        conn, "Spec", status="dispatched", owner="bootstrap",
        body="slugify spec - see templates/spec.md Example 1",
        criteria_json=json.dumps(crit),
        feedback_loop=(
            "If a user reports a slug bug, we write a regression test and "
            "open a PR fixing it."
        ),
        scope="scratch-project",
    )

    # 4. Validate the spec - gate must pass.
    spec_dict = {
        "criteria_json": json.dumps(crit),
        "feedback_loop": (
            "If a user reports a slug bug, we write a regression test and "
            "open a PR fixing it."
        ),
    }
    ok, reasons = validators.validate_spec(spec_dict)
    assert ok, f"spec failed validation: {reasons}"

    # 5. Spec-checker simulation: run each verify command, mark or log.
    any_failed = False
    for i, c in enumerate(crit):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"] + c["verify"].split()[1:],
            cwd=project, capture_output=True, text=True,
        )
        if result.returncode == 0:
            findings.mark_criterion_satisfied(
                conn, spec_id, i,
                evidence=result.stdout.strip()[-200:] or "pytest exit 0",
            )
        else:
            any_failed = True
            findings.log_finding(
                conn, spec_id, "Critical",
                body=(
                    f"criterion {i} failed: {c['text']}\n"
                    f"cmd: {c['verify']}\n"
                    f"stdout:\n{result.stdout[-500:]}\n"
                    f"stderr:\n{result.stderr[-500:]}"
                ),
            )

    # 6. Log the round-trip Strength evidence if all passed.
    if not any_failed:
        findings.log_finding(
            conn, spec_id, "Strength",
            body="bootstrap e2e: all 3 slugify criteria satisfied",
        )

    conn.close()

    # 7. CRITICAL: reopen the DB to prove survival across sessions.
    conn2 = db.connect(db_path)
    reread_spec = nodes.get_node(conn2, spec_id)
    assert reread_spec is not None
    reread_crit = json.loads(reread_spec["criteria_json"])
    assert all(c["satisfied"] for c in reread_crit), (
        f"not all criteria satisfied after reload: {reread_crit}"
    )

    # 8. A Finding (Strength) must exist with evidence.
    findings_rows = conn2.execute(
        "SELECT severity, body FROM finding WHERE parent_id=?", (spec_id,)
    ).fetchall()
    severities = [r[0] for r in findings_rows]
    assert "Strength" in severities, f"no Strength finding logged: {severities}"
    conn2.close()

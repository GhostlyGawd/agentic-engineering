"""Structural guards for Phase 1 agent + command markdown.

These do not run the agents (that is the llm-gated e2e). They assert the docs
exist, have valid frontmatter (no BOM, name+description), and contain the
load-bearing sections each role's design calls for.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _doc(rel: str) -> str:
    text = (REPO / rel).read_text(encoding="utf-8")
    assert text.startswith("---"), f"{rel}: missing/empty frontmatter (BOM?)"
    return text


def test_builder_has_loop_fix_mode():
    t = _doc("agents/builder.md")
    assert "name: builder" in t
    low = t.lower()
    assert "loop-fix" in low
    assert "root cause" in low
    assert "per iteration" in low or "one commit per iteration" in low
    assert "log_retro" in t
    # Loop control stays on the Claude side; builder must not advance/resolve.
    assert "advance_critical_loop" not in t
    assert "resolve_critical_loop" not in t


def test_code_reviewer_doc():
    t = _doc("agents/code-reviewer.md")
    assert "name: code-reviewer" in t
    for sev in ("Critical", "Important", "Suggested", "Strength"):
        assert sev in t
    assert "record_triage" in t
    low = t.lower()
    assert "contrarian" in low and "blind" in low


def test_contrarian_doc():
    t = _doc("agents/contrarian.md")
    assert "name: contrarian" in t
    low = t.lower()
    assert "assume" in low and "wrong" in low
    assert "assumption" in low or "architect" in low
    assert "code-reviewer" in low and "blind" in low
    assert "log_finding" in t


def test_spec_writer_doc():
    t = _doc("agents/spec-writer.md")
    assert "name: spec-writer" in t
    assert "skills/spec-writing/SKILL.md" in t
    assert "validate_spec" in t
    low = t.lower()
    assert "socratic" in low
    assert "retry" in low or "attempts" in low
    assert "escalate" in low or "surface" in low


def test_dispatch_command_doc():
    t = _doc("commands/dispatch.md")
    low = t.lower()
    assert "argument-hint" in low
    assert "validate_spec" in t and "dispatch_spec" in t
    assert "builder" in low
    assert "supersede" in low

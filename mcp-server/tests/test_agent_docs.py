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
    assert "model: sonnet" in t
    for sev in ("Critical", "Important", "Suggested", "Strength"):
        assert sev in t
    assert "record_triage" in t
    low = t.lower()
    assert "contrarian" in low and "blind" in low


def test_contrarian_doc():
    t = _doc("agents/contrarian.md")
    assert "name: contrarian" in t
    assert "model: sonnet" in t
    low = t.lower()
    assert "assume" in low and "wrong" in low
    assert "assumption" in low or "architect" in low
    assert "code-reviewer" in low and "blind" in low
    assert "log_finding" in t


def test_spec_writer_doc():
    t = _doc("agents/spec-writer.md")
    assert "name: spec-writer" in t
    assert "model: sonnet" in t
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


def test_review_pr_command_doc():
    t = _doc("commands/review-pr.md")
    low = t.lower()
    assert "spec-checker" in low and "code-reviewer" in low and "contrarian" in low
    assert "parallel" in low and "blind" in low
    assert "start_critical_loop" in t and "advance_critical_loop" in t
    assert "resolve_critical_loop" in t
    assert "diagnostic" in low
    assert "diminishing returns" in low
    assert "log_retro" in t
    assert "loop-id" in low or "loop_id" in low
    assert "gh" in low and "main" in low and "head" in low


def test_new_spec_command_doc():
    t = _doc("commands/new-spec.md")
    low = t.lower()
    assert "argument-hint" in low
    assert "spec-writer" in low
    assert "retry" in low or "escalat" in low or "reasons" in low


def test_orchestrator_doc_declares_single_tick():
    from pathlib import Path
    text = Path(__file__).parents[2].joinpath("agents", "orchestrator.md").read_text(encoding="utf-8")
    assert "model: sonnet" in text
    assert "--once" in text
    assert "implements nothing" in text.lower()


def test_orchestrate_command_doc():
    t = _doc("commands/orchestrate.md")
    low = t.lower()
    # Single-tick contract
    assert "--once" in t
    assert "--pool" in t
    assert "--weed-days" in t
    # Key mechanisms
    assert "flag_stale" in t
    assert "detect_overlap" in t or "detect overlap" in low
    assert "claim_scope" in t or "claim scope" in low
    assert "record_outcome" in t
    assert "adjust_trust" in t
    assert "merge_order" in t or "dag order" in low
    # Policy
    assert "pool" in low and "3" in t
    assert "14" in t


def test_pattern_finder_doc():
    t = _doc("agents/pattern-finder.md")
    assert "name: pattern-finder" in t
    assert "model: sonnet" in t
    assert "create_node" in t and "link_nodes" in t
    assert "derived-from" in t
    low = t.lower()
    assert "coincidence" in low
    assert "genuine" in low or "recurring" in low


def test_find_patterns_command_doc():
    t = _doc("commands/find-patterns.md")
    low = t.lower()
    assert "argument-hint" in low
    assert "pattern" in low
    assert "query_graph" in t
    assert "triage_pattern" in t

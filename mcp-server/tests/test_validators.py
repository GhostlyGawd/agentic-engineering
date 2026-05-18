import json
import pytest
from agentic_mcp import validators


# --- validate_criterion ---

def test_criterion_rejects_empty_verify():
    ok, reasons = validators.validate_criterion("must work", verify="")
    assert not ok
    assert any("verify" in r.lower() for r in reasons)


def test_criterion_rejects_handwave_verify():
    for bad in ["tbd", "todo", "see above", "works correctly", "handled appropriately"]:
        ok, _ = validators.validate_criterion("must work", verify=bad)
        assert not ok, f"should reject: {bad!r}"


def test_criterion_accepts_pytest_command():
    ok, reasons = validators.validate_criterion(
        "function returns 42", verify="pytest tests/test_x.py::test_returns_42 -v"
    )
    assert ok, reasons


def test_criterion_accepts_runtime_signal():
    ok, _ = validators.validate_criterion(
        "no 5xx in prod", verify="logs show zero 5xx errors in the first hour"
    )
    assert ok


def test_criterion_accepts_type_check():
    ok, _ = validators.validate_criterion(
        "module has no Any types", verify="mypy --strict src/x.py reports 0 errors"
    )
    assert ok


# --- validate_feedback_loop ---

def test_feedback_loop_rejects_empty():
    ok, _ = validators.validate_feedback_loop("")
    assert not ok


def test_feedback_loop_rejects_short():
    ok, _ = validators.validate_feedback_loop("works fine")
    assert not ok


def test_feedback_loop_accepts_signal_plus_fix():
    ok, _ = validators.validate_feedback_loop(
        "If users report incorrect totals, open a bug ticket and write a retro."
    )
    assert ok


def test_feedback_loop_rejects_signal_without_fix():
    ok, _ = validators.validate_feedback_loop(
        "We will watch the logs carefully."
    )
    assert not ok


# --- validate_spec ---

def test_validate_spec_happy_path():
    spec = {
        "criteria_json": json.dumps([
            {"text": "x", "verify": "pytest tests/x.py -v", "satisfied": False},
            {"text": "y", "verify": "mypy --strict src/y.py reports 0 errors", "satisfied": False},
        ]),
        "feedback_loop": "If user reports a regression, file a bug and write a retro.",
    }
    ok, reasons = validators.validate_spec(spec)
    assert ok, reasons


def test_validate_spec_rejects_when_any_criterion_fails():
    spec = {
        "criteria_json": json.dumps([
            {"text": "x", "verify": "pytest tests/x.py -v", "satisfied": False},
            {"text": "y", "verify": "tbd", "satisfied": False},
        ]),
        "feedback_loop": "If user reports a regression, file a bug and write a retro.",
    }
    ok, reasons = validators.validate_spec(spec)
    assert not ok
    assert any("criterion" in r.lower() for r in reasons)


def test_validate_spec_rejects_when_feedback_loop_fails():
    spec = {
        "criteria_json": json.dumps([
            {"text": "x", "verify": "pytest tests/x.py -v", "satisfied": False},
        ]),
        "feedback_loop": "tbd",
    }
    ok, reasons = validators.validate_spec(spec)
    assert not ok

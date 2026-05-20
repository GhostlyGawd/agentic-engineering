# fixtures/phase1/stubborn/spec_test.py
"""Spec: parse_duration('1h30m')==5400, '45s'==45, '2h'==7200; '' / garbage raise ValueError."""
import pytest

from parse_duration import parse_duration


def test_seconds():
    assert parse_duration("45s") == 45


def test_hours():
    assert parse_duration("2h") == 7200


def test_combined():
    assert parse_duration("1h30m") == 5400


def test_rejects_empty():
    with pytest.raises(ValueError):
        parse_duration("")


def test_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("banana")

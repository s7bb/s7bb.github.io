"""Tests for preflight.py."""

import pytest

from s7bb_fetcher import preflight
from s7bb_fetcher.preflight import Check, PreflightFailed, Severity


def test_module_exports_expected_symbols():
    assert hasattr(preflight, "run")
    assert hasattr(preflight, "Check")
    assert hasattr(preflight, "Severity")
    assert hasattr(preflight, "PreflightFailed")


def test_severity_has_hard_and_soft():
    assert Severity.HARD != Severity.SOFT


def test_check_is_dataclass_with_fields():
    c = Check(name="x", severity=Severity.HARD, ok=True, message="fine")
    assert c.name == "x"
    assert c.severity is Severity.HARD
    assert c.ok is True
    assert c.message == "fine"


def test_preflight_failed_is_exception():
    with pytest.raises(PreflightFailed):
        raise PreflightFailed("boom")

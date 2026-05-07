"""Tests for preflight.py."""

import pytest

from s7bb_fetcher import preflight
from s7bb_fetcher.preflight import Check, PreflightFailed, Severity, _check_data_writable


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


def test_data_writable_ok(tmp_path):
    c = _check_data_writable(tmp_path)
    assert c.ok is True
    assert c.severity is Severity.HARD
    assert c.name == "data_writable"


def test_data_writable_missing_dir(tmp_path):
    c = _check_data_writable(tmp_path / "does_not_exist")
    assert c.ok is False
    assert "does not exist" in c.message.lower() or "not found" in c.message.lower()


def test_data_writable_readonly(tmp_path):
    tmp_path.chmod(0o500)
    try:
        c = _check_data_writable(tmp_path)
        assert c.ok is False
        assert "permission" in c.message.lower() or "denied" in c.message.lower()
    finally:
        tmp_path.chmod(0o700)


def test_data_writable_leaves_no_residue(tmp_path):
    _check_data_writable(tmp_path)
    assert list(tmp_path.iterdir()) == []

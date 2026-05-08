import json
from pathlib import Path
from unittest.mock import patch

import pytest

from s7bb_fetcher import cli, preflight
from s7bb_fetcher.cli import export
from s7bb_fetcher.preflight import Check, Severity


def _seed_db(db_path: Path) -> None:
    from s7bb_fetcher.parser import ArrivalRecord
    from s7bb_fetcher.storage import open_db, upsert_records
    conn = open_db(db_path)
    upsert_records(conn, [
        ArrivalRecord(
            train_id="t1", line="S7", station="Baierbrunn",
            direction="München", direction_bucket="muenchen",
            scheduled_time="2026-04-01T08:00:00+00:00",
            actual_time="2026-04-01T08:00:00+00:00",
            delay_minutes=0, cancelled=False, reason=None,
        ),
    ])


def test_cli_archive_index_flag(tmp_path, capsys):
    db = tmp_path / "s7bb.db"
    _seed_db(db)
    archive_dir = tmp_path / "archive"

    export(["--db", str(db), "--archive", "2026-04", "--out-dir", str(archive_dir)])
    export(["--db", str(db), "--archive-index", "--out-dir", str(archive_dir)])

    idx = json.loads((archive_dir / "index.json").read_text())
    assert any(m["period"] == "2026-04" for m in idx["months"])


def test_cli_refinalize_flag_overwrites_finalized_archive(tmp_path):
    db = tmp_path / "s7bb.db"
    _seed_db(db)
    archive_dir = tmp_path / "archive"

    export(["--db", str(db), "--archive", "2026-04", "--out-dir", str(archive_dir)])
    archive = archive_dir / "2026-04.json"
    data1 = json.loads(archive.read_text())
    assert data1["finalized"] is False

    export([
        "--db", str(db), "--archive", "2026-04",
        "--out-dir", str(archive_dir), "--refinalize",
    ])
    data2 = json.loads(archive.read_text())
    assert data2["finalized"] is True


def test_cli_archive_index_requires_dir(tmp_path):
    db = tmp_path / "s7bb.db"
    _seed_db(db)
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    export(["--db", str(db), "--archive-index", "--out-dir", str(archive_dir)])
    assert (archive_dir / "index.json").exists()


def _checks(*pairs):
    return [Check(name=n, severity=s, ok=ok, message=m) for n, s, ok, m in pairs]


def test_cli_preflight_exits_zero_when_all_ok(capsys):
    fake = _checks(
        ("data_writable", Severity.HARD, True, "ok"),
        ("github", Severity.SOFT, True, "ok"),
    )
    with patch.object(preflight, "run", return_value=fake):
        with pytest.raises(SystemExit) as ei:
            cli.preflight([])
    assert ei.value.code == 0


def test_cli_preflight_exits_one_on_hard_fail(capsys):
    fake = _checks(
        ("data_writable", Severity.HARD, False, "denied"),
        ("github", Severity.SOFT, True, "ok"),
    )
    with patch.object(preflight, "run", return_value=fake):
        with pytest.raises(SystemExit) as ei:
            cli.preflight([])
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "data_writable" in out
    assert "denied" in out


def test_cli_preflight_soft_fail_still_zero(capsys):
    fake = _checks(
        ("data_writable", Severity.HARD, True, "ok"),
        ("github", Severity.SOFT, False, "no token"),
    )
    with patch.object(preflight, "run", return_value=fake):
        with pytest.raises(SystemExit) as ei:
            cli.preflight([])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "github" in out
    assert "no token" in out

from pathlib import Path

from lxml import etree

from s7bb_fetcher.parser import classify_direction, parse_timetable

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> etree._Element:
    return etree.parse(str(FIXTURES / name)).getroot()


def test_on_time_record():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    on_time = next(r for r in records if r.train_id == "trip-S7-002-2605051230")
    assert on_time.delay_minutes == 0
    assert not on_time.cancelled
    assert on_time.station == "Baierbrunn"


def test_delayed_record():
    records = parse_timetable(_load("plan.xml"), _load("changes_delayed.xml"))
    delayed = next(r for r in records if r.train_id == "trip-S7-001-2605051200")
    assert delayed.delay_minutes == 7
    assert not delayed.cancelled


def test_cancelled_record():
    records = parse_timetable(_load("plan.xml"), _load("changes_delayed.xml"))
    cancelled = next(r for r in records if r.train_id == "trip-S7-003-2605051300")
    assert cancelled.cancelled
    assert cancelled.actual_time is None


def test_direction_to_wolfratshausen():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    r = next(r for r in records if r.train_id == "trip-S7-001-2605051200")
    assert "Wolfratshausen" in r.direction


def test_all_records_have_line():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    assert all(r.line for r in records)


def test_direction_bucket_wolfratshausen():
    assert classify_direction("Deisenhofen|Furth|Höllriegelskreuth|Pullach|Wolfratshausen") == "wolfratshausen"


def test_direction_bucket_muenchen_by_terminus():
    assert classify_direction(
        "Buchenhain|Höllriegelskreuth|Pullach|München-Solln|München Hbf Gl.27-36"
    ) == "muenchen"


def test_direction_bucket_muenchen_terminus_only():
    """Terminus alone, no full path."""
    assert classify_direction("München Hbf Gl.27-36") == "muenchen"


def test_direction_bucket_unknown_empty():
    assert classify_direction("") == "unknown"


def test_direction_bucket_unknown_garbage():
    assert classify_direction("Irgendwo|Nirgendwo") == "unknown"


def test_records_have_direction_bucket():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    for r in records:
        assert r.direction_bucket in {"muenchen", "wolfratshausen", "unknown"}


def test_scheduled_time_matches_db_pt():
    """`dp pt` is the public planned departure time; parser surfaces it as-is.

    `<dp pt="2605051259">` (Berlin local 12:59) → UTC 10:59. No shift.
    """
    records = parse_timetable(_load("plan_real.xml"), _load("changes_real.xml"))
    rec = next(r for r in records if r.train_id == "trip-S7-real-001")
    assert rec.scheduled_time == "2026-05-05T10:59:00+00:00"


def test_actual_time_matches_db_ct():
    """`dp ct="2605051300"` (Berlin local 13:00) → UTC 11:00.

    One minute after the planned 12:59 → delay 1 minute.
    """
    records = parse_timetable(_load("plan_real.xml"), _load("changes_real.xml"))
    rec = next(r for r in records if r.train_id == "trip-S7-real-001")
    assert rec.actual_time == "2026-05-05T11:00:00+00:00"
    assert rec.delay_minutes == 1


def test_train_number_parsed_from_tl():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    r = next(r for r in records if r.train_id == "trip-S7-002-2605051230")
    assert r.train_number == "6762"


def test_missing_tl_yields_none_and_row_still_emitted():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    no_tl = next(
        (r for r in records if r.train_id == "trip-S7-004-2605051330"), None
    )
    assert no_tl is not None, "stop without <tl> must still be emitted"
    assert no_tl.train_number is None


def test_accepts_s5_substitute_line_during_stammstrecke_closure():
    """During Munich Stammstrecke construction DB Timetables labels
    S7-Süd trains as 'S5'. Parser must keep them, not drop them."""
    records = parse_timetable(
        _load("plan_s5_substitute.xml"), _load("changes_empty.xml")
    )
    rec = next(
        (r for r in records if r.train_id == "trip-S5-sub-001-2605231200"), None
    )
    assert rec is not None, "S5-labelled Munich-bound stop must be parsed"
    assert rec.direction_bucket == "muenchen"
    assert rec.dp_ppth.endswith("München Hbf Gl.27-36")


def test_dp_ppth_preserved_on_record():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    munich_bound = [r for r in records if r.direction_bucket == "muenchen"]
    assert munich_bound, "fixture must contain at least one München-bound stop"
    r = munich_bound[0]
    assert r.dp_ppth, "dp_ppth must be populated"
    # ppth is ordered Baierbrunn → terminus, pipe-separated
    parts = r.dp_ppth.split("|")
    assert parts[-1].startswith("München"), f"last stop should be München, got {parts[-1]}"

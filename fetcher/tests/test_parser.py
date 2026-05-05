from pathlib import Path

from lxml import etree

from s7bb_fetcher.parser import parse_timetable

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

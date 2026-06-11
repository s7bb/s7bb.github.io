from pathlib import Path

from lxml import etree

from s7bb_fetcher.parser import classify_direction, extract_disruption, parse_timetable

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


def test_direction_bucket_muenchen_via_stammstrecke_to_kreuzstrasse():
    """S5 substitute route during Stammstrecke closure: train passes through
    Munich (low-level Stammstrecke) and continues to a S7-Nord terminus.
    Munich is mid-path, terminus is east of the city — still Munich-direction
    for our purposes."""
    path = (
        "Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf|"
        "München-Solln|München Siemenswerke|München-Mittersendling|"
        "München Hbf (tief)|München Karlsplatz|München Marienplatz|"
        "München Ost|München-Giesing|München-Neuperlach Süd|"
        "Neubiberg|Ottobrunn|Hohenbrunn|Höhenkirchen-Siegertsbrunn|"
        "Aying|Peiß|Großhelfendorf|Kreuzstraße"
    )
    assert classify_direction(path) == "muenchen"


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


def _s(xml: str) -> etree._Element:
    return etree.fromstring(xml)


def test_extract_trip_level_him_category_and_window():
    s = _s(
        '<s id="x">'
        '<m id="r1" t="h" from="2606100619" to="2606100830" cat="Störung" pr="1"/>'
        '<ar ct="2606100735" cs="c" l="S7"/>'
        '</s>'
    )
    d = extract_disruption(s)
    assert d.category == "Störung"
    # 2606100619 Europe/Berlin (CEST, +02:00) -> 04:19 UTC
    assert d.window_from == "2026-06-10T04:19:00+00:00"
    assert d.window_to == "2026-06-10T06:30:00+00:00"


def test_extract_stop_level_cause_code():
    s = _s(
        '<s id="x"><ar l="S7">'
        '<m id="r2" t="d" c="34"/>'
        '<m id="r3" t="f" c="0"/>'
        '</ar></s>'
    )
    d = extract_disruption(s)
    assert d.cause_code == 34
    assert d.category is None


def test_extract_ignores_f_and_zero_codes():
    s = _s('<s id="x"><dp l="S7"><m t="f" c="0"/><m t="d" c="0"/></dp></s>')
    assert extract_disruption(s) is None


def test_extract_ar_wins_over_dp_for_cause_code():
    s = _s(
        '<s id="x">'
        '<ar l="S7"><m t="d" c="34"/></ar>'
        '<dp l="S7"><m t="d" c="44"/></dp>'
        '</s>'
    )
    assert extract_disruption(s).cause_code == 34


def test_extract_none_when_no_messages():
    s = _s('<s id="x"><ar l="S7"/><dp l="S7"/></s>')
    assert extract_disruption(s) is None


def test_extract_malformed_window_bound_becomes_none():
    s = _s('<s id="x"><m t="h" from="garbage" to="2606100830" cat="Störung"/></s>')
    d = extract_disruption(s)
    assert d.category == "Störung"
    assert d.window_from is None
    assert d.window_to == "2026-06-10T06:30:00+00:00"


def test_parse_sets_disruption_on_disrupted_row(tmp_path):
    # Build a changes XML carrying a HIM message + cause code for an existing plan trip id.
    plan = _load("plan.xml")
    sid = "trip-S7-001-2605051200"
    changes = _s(
        f'<timetable><s id="{sid}">'
        '<m t="h" from="2605051150" to="2605051300" cat="Störung"/>'
        '<ar l="S7"><m t="d" c="34"/></ar>'
        '<dp l="S7" ct="2605051207"/>'
        "</s></timetable>"
    )
    records = parse_timetable(plan, changes)
    r = next(r for r in records if r.train_id == sid)
    assert r.disruption is not None
    assert r.disruption.category == "Störung"
    assert r.disruption.cause_code == 34
    assert r.reason is None  # legacy field retired, always None


def test_parse_disruption_none_for_on_time():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    on_time = next(r for r in records if r.train_id == "trip-S7-002-2605051230")
    assert on_time.disruption is None
    assert on_time.reason is None

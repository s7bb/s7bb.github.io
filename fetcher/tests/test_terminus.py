from datetime import UTC, datetime, timedelta
from pathlib import Path

from lxml import etree

from s7bb_fetcher.parser import ArrivalRecord
from s7bb_fetcher.storage import open_db, upsert_records
from s7bb_fetcher.terminus import PendingTrain

FIXTURES = Path(__file__).parent / "fixtures"

# Trip-id prefix shared by every fixture (s/@id without the per-station
# stop-sequence tail). Baierbrunn's stop sequence is "-5" in these tests;
# terminus fixtures use "-22" (Munich) or "-34" (Wolfratshausen).
TRIP_PREFIX = "42-2605051200"
BAIERBRUNN_ID = f"{TRIP_PREFIX}-5"

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


def _load(name: str) -> etree._Element:
    return etree.fromstring((FIXTURES / name).read_bytes(), parser=_PARSER)


def test_trip_prefix_strips_last_segment():
    from s7bb_fetcher.terminus import trip_prefix
    assert trip_prefix("42-2605051200-5") == "42-2605051200"
    # Negative leading int (real DB IDs do this) — last "-" still wins
    assert trip_prefix("-755312524326409208-2605222211-33") == "-755312524326409208-2605222211"
    assert trip_prefix("") == ""
    # Single-token id has no separator → empty string (skip)
    assert trip_prefix("nope") == ""


def test_build_index_keys_by_trip_prefix():
    from s7bb_fetcher.terminus import build_index
    idx = build_index(_load("terminus_munich_arrived.xml"))
    assert TRIP_PREFIX in idx
    assert idx[TRIP_PREFIX].tag == "s"


def test_build_index_skips_entries_without_usable_id():
    from s7bb_fetcher.terminus import build_index
    xml = etree.fromstring(
        b'<timetable><s id=""><ar pt="2605051200"/></s>'
        b'<s id="single"><ar pt="2605051200"/></s></timetable>',
        parser=_PARSER,
    )
    assert build_index(xml) == {}


def test_is_cancelled_true_on_ar_cs_c():
    from s7bb_fetcher.terminus import _is_cancelled, build_index
    entry = build_index(_load("terminus_munich_cancelled.xml"))[TRIP_PREFIX]
    assert _is_cancelled(entry) is True


def test_is_cancelled_false_on_normal_arrival():
    from s7bb_fetcher.terminus import _is_cancelled, build_index
    entry = build_index(_load("terminus_munich_arrived.xml"))[TRIP_PREFIX]
    assert _is_cancelled(entry) is False


def test_constants_present():
    from s7bb_fetcher import terminus
    assert terminus.MUENCHEN_HBF_EVA == "8098261"
    assert terminus.WOLFRATSHAUSEN_EVA == "8006550"
    assert terminus.CUTOFF_GRACE_MINUTES == 60
    assert terminus.TRAVEL_TIME_MINUTES == {"muenchen": 35, "wolfratshausen": 20}
    # Spot-check the station→EVA table from the spec
    assert terminus.STATION_NAME_TO_EVA["München-Solln"] == "8004161"
    assert terminus.STATION_NAME_TO_EVA["Hohenschäftlarn"] == "8002955"
    assert terminus.STATION_NAME_TO_EVA["München Hbf Gl.27-36"] == "8098261"


def _pending(
    train_id=BAIERBRUNN_ID,
    scheduled_iso="2026-05-05T10:30:00+00:00",
    bucket="muenchen",
    dp_ppth="Buchenhain|Höllriegelskreuth|München Hbf Gl.27-36",
) -> PendingTrain:
    return PendingTrain(train_id, scheduled_iso, bucket, dp_ppth)


# scheduled_time is 10:30 UTC; cutoff = 10:30 + 35 + 60 = 12:05 UTC
_BEFORE_CUTOFF = datetime(2026, 5, 5, 11, 30, tzinfo=UTC)
_AFTER_CUTOFF  = datetime(2026, 5, 5, 13,  0, tzinfo=UTC)


def test_classify_arrived_on_time():
    from s7bb_fetcher.terminus import build_index, classify, trip_prefix
    idx = build_index(_load("terminus_munich_arrived.xml"))
    pending = _pending()
    update = classify(pending, idx.get(trip_prefix(pending.train_id)), _BEFORE_CUTOFF,
                      drilldown=lambda *_: None)
    assert update is not None
    assert update.terminus_status == "arrived"
    # Fixture has only ct (no pt) → delay falls back to 0.
    assert update.terminus_delay_minutes == 0
    assert update.terminus_short_turn_station is None


def test_classify_arrived_with_delay():
    from s7bb_fetcher.terminus import build_index, classify, trip_prefix
    idx = build_index(_load("terminus_munich_delayed.xml"))
    pending = _pending()
    update = classify(pending, idx.get(trip_prefix(pending.train_id)), _BEFORE_CUTOFF,
                      drilldown=lambda *_: None)
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 5


def test_classify_short_turn_calls_drilldown_and_uses_its_result():
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_cancelled.xml"))
    calls = []

    def fake_drilldown(dp_ppth, train_id):
        calls.append((dp_ppth, train_id))
        return "München-Solln"

    update = classify(_pending(), idx.get(TRIP_PREFIX), _BEFORE_CUTOFF,
                      drilldown=fake_drilldown)
    assert calls == [("Buchenhain|Höllriegelskreuth|München Hbf Gl.27-36", BAIERBRUNN_ID)]
    assert update.terminus_status == "short_turn"
    assert update.terminus_short_turn_station == "München-Solln"
    assert update.terminus_delay_minutes is None


def test_classify_cancelled_when_drilldown_finds_no_intermediate():
    """Terminus says cs='c' but no intermediate station reports the train
    as cancelled → train vanished entirely → status='cancelled'."""
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_cancelled.xml"))
    update = classify(_pending(), idx.get(TRIP_PREFIX), _BEFORE_CUTOFF,
                      drilldown=lambda *_: None)
    assert update.terminus_status == "cancelled"
    assert update.terminus_short_turn_station is None


def test_classify_pending_when_missing_before_cutoff():
    """Train absent from terminus feed but cutoff not yet passed → return
    None (= no update; row stays 'pending' until next cycle)."""
    from s7bb_fetcher.terminus import classify
    assert classify(_pending(), None, _BEFORE_CUTOFF,
                    drilldown=lambda *_: None) is None


def test_classify_short_turn_via_drilldown_after_cutoff():
    """Missing past cutoff + drilldown finds a cancelled intermediate →
    short_turn."""
    from s7bb_fetcher.terminus import classify
    update = classify(_pending(), None, _AFTER_CUTOFF,
                      drilldown=lambda *_: "Pullach")
    assert update.terminus_status == "short_turn"
    assert update.terminus_short_turn_station == "Pullach"


def test_classify_cancelled_when_missing_past_cutoff_and_drilldown_blank():
    from s7bb_fetcher.terminus import classify
    update = classify(_pending(), None, _AFTER_CUTOFF,
                      drilldown=lambda *_: None)
    assert update.terminus_status == "cancelled"
    assert update.terminus_short_turn_station is None


def test_classify_wolfratshausen_uses_20_minute_travel_time():
    """Wolfratshausen cutoff = scheduled + 20 + 60 = +80 min. A train missing
    at scheduled + 70 min must still be 'pending', not 'cancelled'."""
    from s7bb_fetcher.terminus import classify
    pending = _pending(bucket="wolfratshausen",
                       dp_ppth="Hohenschäftlarn|Ebenhausen-Schäftlarn|Icking|Wolfratshausen")
    sched = datetime.fromisoformat(pending.scheduled_time)
    now = sched + timedelta(minutes=70)
    assert classify(pending, None, now, drilldown=lambda *_: None) is None


def test_classify_arrived_zero_delay_when_ct_missing():
    """An entry without ct (e.g. only carrying station-level messages) is
    treated as arrived with delay=0."""
    from s7bb_fetcher.terminus import classify
    xml = etree.fromstring(
        b'<timetable><s id="42-2605051200-22"><ar pt="2605051230"/></s></timetable>',
        parser=_PARSER,
    )
    entry = xml.find(".//s")
    update = classify(_pending(), entry, _BEFORE_CUTOFF, drilldown=lambda *_: None)
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 0


class _FakeClient:
    """Duck-typed stand-in for api module: maps eva → /fchg fixture name."""

    def __init__(self, mapping: dict[str, str]):
        # mapping: eva → fixture filename (without .xml)
        self._mapping = mapping
        self.calls: list[str] = []

    def fetch_full_changes(self, eva: str) -> etree._Element:
        self.calls.append(eva)
        name = self._mapping.get(eva)
        if name is None:
            raise AssertionError(f"unexpected fetch for eva={eva}")
        return _load(name + ".xml")

    def fetch_plan(self, eva: str, date: str, hour: str) -> etree._Element:
        # No-op for orchestrator tests that don't care about plan-pt: every
        # delay assertion in pre-existing tests is 0 anyway, so an empty
        # timetable yields an empty plan_pt index.
        return etree.fromstring(b"<timetable/>", parser=_PARSER)


def test_drilldown_returns_baierbrunn_most_cancelled():
    """Solln has cs='c'; stations before Solln are not in /fchg (on-time
    pass-through) → first reverse-walk None breaks the loop → return Solln."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_cancelled",  # München-Solln cancelled
        # Stations earlier in ppth return empty /fchg feeds.
        "8004899": "empty_fchg",
        "8002899": "empty_fchg",
        "8071272": "empty_fchg",
        "8002422": "empty_fchg",
    })
    ppth = "Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf|München-Solln|München Hbf Gl.27-36"
    result = drilldown_short_turn(client, ppth, BAIERBRUNN_ID)
    assert result == "München-Solln"


def test_drilldown_stops_at_first_on_time_intermediate():
    """If München-Solln is present in /fchg WITHOUT cs='c' (i.e. delayed
    but ran), the walk stops there — Pullach (earlier) is never fetched."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_arrived",  # delayed, not cancelled
    })
    ppth = "Pullach|München-Solln|München Hbf Gl.27-36"
    result = drilldown_short_turn(client, ppth, BAIERBRUNN_ID)
    assert result is None
    # Pullach (8004899) must NOT be fetched
    assert "8004899" not in client.calls


def test_drilldown_unknown_station_logs_and_continues(caplog):
    """An unknown station name is skipped without aborting the walk."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_cancelled",
    })
    ppth = "Mars|München-Solln|München Hbf Gl.27-36"
    with caplog.at_level("WARNING"):
        result = drilldown_short_turn(client, ppth, BAIERBRUNN_ID)
    assert result == "München-Solln"
    assert any("Mars" in r.message for r in caplog.records)


def test_drilldown_empty_ppth_returns_none():
    """Legacy rows with NULL/empty dp_ppth cannot be drilled down."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({})
    assert drilldown_short_turn(client, "", BAIERBRUNN_ID) is None
    assert drilldown_short_turn(client, None, BAIERBRUNN_ID) is None
    assert client.calls == []


def test_drilldown_unusable_train_id_returns_none():
    """A train_id with no separator yields an empty prefix → skip entirely."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({})
    assert drilldown_short_turn(client, "X|München Hbf Gl.27-36", "nope") is None
    assert client.calls == []


def test_drilldown_http_error_aborts_walk_and_returns_none():
    """A transient HTTP failure mid-walk leaves the train pending (caller
    interprets None correctly)."""
    from s7bb_fetcher.terminus import drilldown_short_turn

    class _Erroring:
        def fetch_full_changes(self, eva):
            raise RuntimeError("boom")
    ppth = "München-Solln|München Hbf Gl.27-36"
    assert drilldown_short_turn(_Erroring(), ppth, BAIERBRUNN_ID) is None


def _arr(**kw) -> ArrivalRecord:
    defaults = dict(
        train_id=kw.get("train_id", BAIERBRUNN_ID),
        line="S7", station="Baierbrunn", direction="München Hbf Gl.27-36",
        direction_bucket="muenchen",
        scheduled_time="2026-05-05T10:00:00+00:00",
        actual_time="2026-05-05T10:00:00+00:00", delay_minutes=0,
        cancelled=False, reason=None, train_number="6762",
        dp_ppth="Buchenhain|München Hbf Gl.27-36",
    )
    return ArrivalRecord(**{**defaults, **kw})


def test_list_pending_excludes_cancelled(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [
        _arr(train_id="t1", cancelled=False),
        _arr(train_id="t2", cancelled=True,
             actual_time=None, delay_minutes=None),
    ])
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    pending = list_pending_trains(conn, now)
    ids = {p.train_id for p in pending}
    assert ids == {"t1"}


def test_list_pending_excludes_terminal_states(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(train_id="t1")])
    conn.execute("UPDATE arrivals SET terminus_status='arrived'")
    conn.commit()
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    assert list_pending_trains(conn, now) == []


def test_list_pending_window_scope(tmp_path):
    """Window is [now-2h, now+5min]. Older than 2h or in the future > 5min is excluded."""
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [
        _arr(train_id="old",    scheduled_time="2026-05-05T07:00:00+00:00"),  # 3h ago
        _arr(train_id="now",    scheduled_time="2026-05-05T09:30:00+00:00"),  # in window
        _arr(train_id="future", scheduled_time="2026-05-05T11:00:00+00:00"),  # +1h
    ])
    now = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)
    pending = list_pending_trains(conn, now)
    ids = {p.train_id for p in pending}
    assert ids == {"now"}


def test_list_pending_returns_dataclass_fields(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(train_id="t1",
                                dp_ppth="X|München Hbf Gl.27-36")])
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    [p] = list_pending_trains(conn, now)
    assert p.train_id == "t1"
    assert p.direction_bucket == "muenchen"
    assert p.dp_ppth == "X|München Hbf Gl.27-36"


def test_update_terminus_for_window_writes_arrived(tmp_path):
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id=BAIERBRUNN_ID,
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8098261": "terminus_munich_arrived"})
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    n = update_terminus_for_window(conn, client, now=now)
    assert n == 1
    row = conn.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals"
    ).fetchone()
    assert row == ("arrived", 0)


def test_update_terminus_for_window_skips_quiet_directions(tmp_path):
    """Only directions with pending trains are polled. With one Wolfratshausen-
    bound pending train, München's /fchg must not be fetched."""
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id=BAIERBRUNN_ID,
        direction="Wolfratshausen", direction_bucket="wolfratshausen",
        dp_ppth="Hohenschäftlarn|Wolfratshausen",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8006550": "terminus_wolfratshausen_arrived"})
    # München (8098261) is NOT in the mapping; if it were fetched the
    # _FakeClient would assert. The test passes iff it isn't fetched.
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    n = update_terminus_for_window(conn, client, now=now)
    assert n == 1
    assert "8098261" not in client.calls


def test_update_terminus_for_window_logs_zero_match_streak(tmp_path, caplog):
    """3 consecutive zero-match cycles with non-empty pending list logs a WARN
    about possible EVA mismatch; the streak is persisted to terminus_health."""
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    # train_id whose prefix is NOT in the fixture → zero match
    upsert_records(conn, [_arr(
        train_id="9999-2605051200-5",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8098261": "terminus_munich_arrived"})  # has 42-2605051200, not 9999-*
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)

    with caplog.at_level("WARNING"):
        update_terminus_for_window(conn, client, now=now)
        update_terminus_for_window(conn, client, now=now)
        update_terminus_for_window(conn, client, now=now)

    streak = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE eva='8098261'"
    ).fetchone()
    assert streak[0] == 3
    assert any("0 matches against eva=8098261" in r.message for r in caplog.records)


def test_update_terminus_for_window_resets_streak_on_match(tmp_path):
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    # First: zero-match cycle (prefix 9999-* not in fixture)
    upsert_records(conn, [_arr(
        train_id="9999-2605051200-5",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8098261": "terminus_munich_arrived"})
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    update_terminus_for_window(conn, client, now=now)
    # Then: matching cycle (42-2605051200 is in the fixture)
    upsert_records(conn, [_arr(
        train_id=BAIERBRUNN_ID,
        scheduled_time="2026-05-05T10:35:00+00:00",
    )])
    update_terminus_for_window(conn, client, now=now)
    streak = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE eva='8098261'"
    ).fetchone()
    assert streak[0] == 0


def test_update_terminus_for_window_returns_zero_when_no_pending(tmp_path):
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    client = _FakeClient({})  # nothing should be fetched
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    assert update_terminus_for_window(conn, client, now=now) == 0
    assert client.calls == []


def test_build_plan_pt_index_keys_by_trip_prefix_and_uses_ar_pt():
    from s7bb_fetcher.terminus import _build_plan_pt_index
    idx = _build_plan_pt_index(_load("terminus_munich_plan.xml"))
    assert idx == {TRIP_PREFIX: "2605051340"}


def test_build_plan_pt_index_skips_blocks_without_ar_or_id():
    from s7bb_fetcher.terminus import _build_plan_pt_index
    xml = etree.fromstring(
        b'<timetable>'
        b'  <s id=""><ar pt="2605051340"/></s>'           # bad id
        b'  <s id="single"><ar pt="2605051340"/></s>'     # no separator
        b'  <s id="42-2605051200-22"></s>'                # no ar
        b'  <s id="42-2605051200-22"><ar/></s>'           # ar without pt
        b'</timetable>',
        parser=_PARSER,
    )
    assert _build_plan_pt_index(xml) == {}


def test_hour_keys_dedups_and_uses_terminus_local_hour():
    """Two pending trains 10 min apart at Baierbrunn, same target hour at
    München (10:30 UTC + 35 min ≈ 13:05 Berlin; 10:40 UTC + 35 min ≈
    13:15 Berlin) → both fall into the same (date, "13") plan hour."""
    from s7bb_fetcher.terminus import _hour_keys
    group = [
        _pending(scheduled_iso="2026-05-05T10:30:00+00:00"),
        _pending(scheduled_iso="2026-05-05T10:40:00+00:00"),
    ]
    assert _hour_keys(group, bucket="muenchen") == {("260505", "13")}


def test_hour_keys_spans_two_hours_when_pending_straddles_boundary():
    from s7bb_fetcher.terminus import _hour_keys
    # 11:00 UTC + 35 min = 13:35 Berlin (CEST) → "13"
    # 11:30 UTC + 35 min = 14:05 Berlin (CEST) → "14"
    group = [
        _pending(scheduled_iso="2026-05-05T11:00:00+00:00"),
        _pending(scheduled_iso="2026-05-05T11:30:00+00:00"),
    ]
    assert _hour_keys(group, bucket="muenchen") == {("260505", "13"), ("260505", "14")}


def test_hour_keys_uses_wolfratshausen_offset():
    from s7bb_fetcher.terminus import _hour_keys
    # 11:00 UTC + 20 min = 13:20 Berlin → "13"
    group = [_pending(scheduled_iso="2026-05-05T11:00:00+00:00", bucket="wolfratshausen")]
    assert _hour_keys(group, bucket="wolfratshausen") == {("260505", "13")}


def test_arrival_delay_uses_fchg_pt_when_present():
    """If /fchg carries pt (long-distance services do), it wins over the plan fallback."""
    from s7bb_fetcher.terminus import _arrival_delay_minutes, build_index
    entry = build_index(_load("terminus_munich_delayed.xml"))[TRIP_PREFIX]
    # planned_pt argument is ignored when entry has pt
    assert _arrival_delay_minutes(entry, planned_pt="2605059999") == 5


def test_arrival_delay_falls_back_to_planned_pt_when_fchg_lacks_it():
    from s7bb_fetcher.terminus import _arrival_delay_minutes, build_index
    entry = build_index(_load("terminus_munich_delayed_no_pt.xml"))[TRIP_PREFIX]
    assert _arrival_delay_minutes(entry, planned_pt="2605051340") == 5


def test_arrival_delay_returns_zero_when_no_pt_anywhere():
    from s7bb_fetcher.terminus import _arrival_delay_minutes, build_index
    entry = build_index(_load("terminus_munich_delayed_no_pt.xml"))[TRIP_PREFIX]
    assert _arrival_delay_minutes(entry, planned_pt=None) == 0


def test_arrival_delay_returns_zero_when_ct_missing():
    from s7bb_fetcher.terminus import _arrival_delay_minutes
    xml = etree.fromstring(
        b'<timetable><s id="42-2605051200-22"><ar/></s></timetable>',
        parser=_PARSER,
    )
    entry = xml.find(".//s")
    assert _arrival_delay_minutes(entry, planned_pt="2605051340") == 0


def test_classify_arrived_uses_planned_pt_for_delay():
    from s7bb_fetcher.terminus import build_index, classify, trip_prefix
    idx = build_index(_load("terminus_munich_delayed_no_pt.xml"))
    pending = _pending()
    update = classify(
        pending,
        idx.get(trip_prefix(pending.train_id)),
        _BEFORE_CUTOFF,
        drilldown=lambda *_: None,
        planned_pt="2605051340",
    )
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 5


def test_update_terminus_for_window_uses_plan_pt_for_delay(tmp_path):
    """End-to-end: pending row, fake client returns /fchg without pt + /plan
    with pt → delay 5 written to DB."""
    from s7bb_fetcher.terminus import update_terminus_for_window

    db = open_db(tmp_path / "s.db")
    # Insert a pending row matching TRIP_PREFIX, scheduled 10:30 UTC München-bound.
    sched_iso = "2026-05-05T10:30:00+00:00"
    upsert_records(db, [ArrivalRecord(
        train_id=BAIERBRUNN_ID, line="S7", station="Baierbrunn",
        direction="München Hbf Gl.27-36", direction_bucket="muenchen",
        scheduled_time=sched_iso, actual_time=sched_iso, delay_minutes=0,
        cancelled=False, reason=None, train_number="6042",
        dp_ppth="Buchenhain|München Hbf Gl.27-36",
    )])

    class FakeClient:
        def __init__(self):
            self.plan_calls: list[tuple[str, str, str]] = []
            self.fchg_calls: list[str] = []
        def fetch_plan(self, eva, date, hour):
            self.plan_calls.append((eva, date, hour))
            return _load("terminus_munich_plan.xml")
        def fetch_full_changes(self, eva):
            self.fchg_calls.append(eva)
            return _load("terminus_munich_delayed_no_pt.xml")

    client = FakeClient()
    # now must be after Baierbrunn departure so the pending row is in window.
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    written = update_terminus_for_window(db, client, now=now)

    assert written == 1
    # Plan was called for the München terminus EVA at the expected Berlin hour.
    # 10:30 UTC + 35 min = 13:05 Berlin (CEST) → hour "13"
    assert client.plan_calls == [("8098261", "260505", "13")]
    assert client.fchg_calls == ["8098261"]

    row = db.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals WHERE train_id=?",
        (BAIERBRUNN_ID,),
    ).fetchone()
    assert row == ("arrived", 5)


def test_update_terminus_for_window_tolerates_plan_http_error(tmp_path):
    """If /plan raises, the cycle still completes; delay falls back to 0."""
    from s7bb_fetcher.terminus import update_terminus_for_window

    db = open_db(tmp_path / "s.db")
    sched_iso = "2026-05-05T10:30:00+00:00"
    upsert_records(db, [ArrivalRecord(
        train_id=BAIERBRUNN_ID, line="S7", station="Baierbrunn",
        direction="München Hbf Gl.27-36", direction_bucket="muenchen",
        scheduled_time=sched_iso, actual_time=sched_iso, delay_minutes=0,
        cancelled=False, reason=None, train_number="6042",
        dp_ppth="Buchenhain|München Hbf Gl.27-36",
    )])

    class FakeClient:
        def fetch_plan(self, *a, **kw):
            raise RuntimeError("boom")
        def fetch_full_changes(self, eva):
            return _load("terminus_munich_delayed_no_pt.xml")

    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    written = update_terminus_for_window(db, FakeClient(), now=now)

    assert written == 1
    row = db.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals WHERE train_id=?",
        (BAIERBRUNN_ID,),
    ).fetchone()
    # arrived; delay falls back to 0 because both /fchg.pt and plan are unavailable
    assert row == ("arrived", 0)

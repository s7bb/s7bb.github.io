from datetime import datetime, timedelta, UTC
from pathlib import Path

from lxml import etree

FIXTURES = Path(__file__).parent / "fixtures"

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


def _load(name: str) -> etree._Element:
    return etree.fromstring((FIXTURES / name).read_bytes(), parser=_PARSER)


def test_build_index_keys_by_train_number():
    from s7bb_fetcher.terminus import build_index
    idx = build_index(_load("terminus_munich_arrived.xml"))
    assert "6762" in idx
    assert idx["6762"].tag == "s"


def test_build_index_skips_entries_without_tl_n():
    """A <s> without a train number is skipped (cannot be matched)."""
    from s7bb_fetcher.terminus import build_index
    xml = etree.fromstring(
        b'<timetable><s id="x"><ar pt="2605051200"/></s></timetable>',
        parser=_PARSER,
    )
    assert build_index(xml) == {}


def test_is_cancelled_true_on_ar_cs_c():
    from s7bb_fetcher.terminus import _is_cancelled, build_index
    entry = build_index(_load("terminus_munich_cancelled.xml"))["6762"]
    assert _is_cancelled(entry) is True


def test_is_cancelled_false_on_normal_arrival():
    from s7bb_fetcher.terminus import _is_cancelled, build_index
    entry = build_index(_load("terminus_munich_arrived.xml"))["6762"]
    assert _is_cancelled(entry) is False


def test_constants_present():
    from s7bb_fetcher import terminus
    assert terminus.MUENCHEN_HBF_EVA == "8000261"
    assert terminus.WOLFRATSHAUSEN_EVA == "8006550"
    assert terminus.CUTOFF_GRACE_MINUTES == 60
    assert terminus.TRAVEL_TIME_MINUTES == {"muenchen": 35, "wolfratshausen": 20}
    # Spot-check the station→EVA table from the spec
    assert terminus.STATION_NAME_TO_EVA["München-Solln"] == "8004161"
    assert terminus.STATION_NAME_TO_EVA["Hohenschäftlarn"] == "8002955"


from s7bb_fetcher.terminus import PendingTrain  # forward-OK after Task 6


def _pending(
    train_number="6762",
    scheduled_iso="2026-05-05T10:30:00+00:00",
    bucket="muenchen",
    dp_ppth="Buchenhain|Höllriegelskreuth|München Hbf Gl.27-36",
) -> PendingTrain:
    return PendingTrain(train_number, scheduled_iso, bucket, dp_ppth)


# scheduled_time is 10:30 UTC; cutoff = 10:30 + 35 + 60 = 12:05 UTC
_BEFORE_CUTOFF = datetime(2026, 5, 5, 11, 30, tzinfo=UTC)
_AFTER_CUTOFF  = datetime(2026, 5, 5, 13,  0, tzinfo=UTC)


def test_classify_arrived_on_time():
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_arrived.xml"))
    pending = _pending()
    update = classify(pending, idx.get(pending.train_number), _BEFORE_CUTOFF,
                      drilldown=lambda *_: None)
    assert update is not None
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 0
    assert update.terminus_short_turn_station is None


def test_classify_arrived_with_delay():
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_delayed.xml"))
    pending = _pending()
    update = classify(pending, idx.get(pending.train_number), _BEFORE_CUTOFF,
                      drilldown=lambda *_: None)
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 5


def test_classify_short_turn_calls_drilldown_and_uses_its_result():
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_cancelled.xml"))
    calls = []

    def fake_drilldown(dp_ppth, train_number):
        calls.append((dp_ppth, train_number))
        return "München-Solln"

    update = classify(_pending(), idx.get("6762"), _BEFORE_CUTOFF,
                      drilldown=fake_drilldown)
    assert calls == [("Buchenhain|Höllriegelskreuth|München Hbf Gl.27-36", "6762")]
    assert update.terminus_status == "short_turn"
    assert update.terminus_short_turn_station == "München-Solln"
    assert update.terminus_delay_minutes is None


def test_classify_cancelled_when_drilldown_finds_no_intermediate():
    """Terminus says cs='c' but no intermediate station reports the train
    as cancelled → train vanished entirely → status='cancelled'."""
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_cancelled.xml"))
    update = classify(_pending(), idx.get("6762"), _BEFORE_CUTOFF,
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
    """Some on-time entries omit ct entirely. With no cs and no ct, treat
    as arrived with delay=0."""
    from s7bb_fetcher.terminus import classify
    xml = etree.fromstring(
        b'<timetable><s id="x"><tl n="6762"/><ar pt="2605051230"/></s></timetable>',
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


def test_drilldown_returns_baierbrunn_most_cancelled():
    """Solln has cs='c'; stations before Solln are not in /fchg (on-time
    pass-through) → first reverse-walk None breaks the loop → return Solln."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_cancelled",  # München-Solln cancelled
        # Stations earlier in ppth (Pullach, Höllriegelskreuth, ...) return
        # empty /fchg feeds. We model that by mapping them to an empty
        # fixture; build_index of an empty <timetable/> yields {}.
        "8004899": "empty_fchg",
        "8002899": "empty_fchg",
        "8071272": "empty_fchg",
        "8002422": "empty_fchg",
    })
    ppth = "Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf|München-Solln|München Hbf Gl.27-36"
    result = drilldown_short_turn(client, ppth, "6762")
    assert result == "München-Solln"


def test_drilldown_stops_at_first_on_time_intermediate():
    """If München-Solln is present in /fchg WITHOUT cs='c' (i.e. delayed
    but ran), the walk stops there — Pullach (earlier) is never fetched."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_arrived",  # delayed, not cancelled
    })
    ppth = "Pullach|München-Solln|München Hbf Gl.27-36"
    result = drilldown_short_turn(client, ppth, "6762")
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
        result = drilldown_short_turn(client, ppth, "6762")
    assert result == "München-Solln"
    assert any("Mars" in r.message for r in caplog.records)


def test_drilldown_empty_ppth_returns_none():
    """Legacy rows with NULL/empty dp_ppth cannot be drilled down."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({})
    assert drilldown_short_turn(client, "", "6762") is None
    assert drilldown_short_turn(client, None, "6762") is None
    assert client.calls == []


def test_drilldown_http_error_aborts_walk_and_returns_none():
    """A transient HTTP failure mid-walk leaves the train pending (caller
    interprets None correctly)."""
    from s7bb_fetcher.terminus import drilldown_short_turn

    class _Erroring:
        def fetch_full_changes(self, eva):
            raise RuntimeError("boom")
    ppth = "München-Solln|München Hbf Gl.27-36"
    assert drilldown_short_turn(_Erroring(), ppth, "6762") is None


from s7bb_fetcher.parser import ArrivalRecord
from s7bb_fetcher.storage import open_db, upsert_records


def _arr(**kw) -> ArrivalRecord:
    defaults = dict(
        train_id=kw.get("train_id", "t1"),
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
        _arr(train_id="t1", train_number="A", cancelled=False),
        _arr(train_id="t2", train_number="B", cancelled=True,
             actual_time=None, delay_minutes=None),
    ])
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    pending = list_pending_trains(conn, now)
    nums = {p.train_number for p in pending}
    assert nums == {"A"}


def test_list_pending_excludes_terminal_states(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(train_id="t1", train_number="A")])
    conn.execute("UPDATE arrivals SET terminus_status='arrived'")
    conn.commit()
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    assert list_pending_trains(conn, now) == []


def test_list_pending_excludes_null_train_number(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(train_id="t1", train_number=None)])
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    assert list_pending_trains(conn, now) == []


def test_list_pending_window_scope(tmp_path):
    """Window is [now-2h, now+5min]. Older than 2h or in the future > 5min is excluded."""
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [
        _arr(train_id="old",   train_number="A", scheduled_time="2026-05-05T07:00:00+00:00"),  # 3h ago
        _arr(train_id="now",   train_number="B", scheduled_time="2026-05-05T09:30:00+00:00"),  # in window
        _arr(train_id="future",train_number="C", scheduled_time="2026-05-05T11:00:00+00:00"),  # +1h
    ])
    now = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)
    pending = list_pending_trains(conn, now)
    nums = {p.train_number for p in pending}
    assert nums == {"B"}


def test_list_pending_returns_dataclass_fields(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(train_id="t1", train_number="A",
                                dp_ppth="X|München Hbf Gl.27-36")])
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    [p] = list_pending_trains(conn, now)
    assert p.train_number == "A"
    assert p.direction_bucket == "muenchen"
    assert p.dp_ppth == "X|München Hbf Gl.27-36"

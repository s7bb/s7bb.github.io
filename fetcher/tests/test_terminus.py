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

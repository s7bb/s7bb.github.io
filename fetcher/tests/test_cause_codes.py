from s7bb_fetcher.cause_codes import decode_cause


def test_known_code_decodes():
    assert decode_cause(34) == "Verspätung eines vorausfahrenden Zuges"


def test_unknown_code_returns_none():
    assert decode_cause(99999) is None


def test_none_returns_none():
    assert decode_cause(None) is None

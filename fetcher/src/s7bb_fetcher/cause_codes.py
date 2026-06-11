"""Decode DB Timetables delay-cause (Verspaetungsursachen) codes to German text.

Lives in code (not the DB) so extending this table re-decodes all historical
rows at export time. Unknown code -> None; the raw cause_code is still emitted
by the exporter, so no information is lost.

Only codes whose meaning is confirmed against the DB Verspaetungsursachen reference
are listed. Omit (number-fallback) rather than guess (see spec).
"""

CAUSE_CODES: dict[int, str] = {
    34: "Verspätung eines vorausfahrenden Zuges",
    # Codes 43, 44, 48 observed in production but not yet confirmed against
    # the DB Verspaetungsursachen reference - left out until confirmed.
}


def decode_cause(code: int | None) -> str | None:
    if code is None:
        return None
    return CAUSE_CODES.get(code)

"""Parse DB Timetables XML into ArrivalRecord dataclasses."""

from dataclasses import dataclass
from datetime import datetime, timezone

from lxml import etree


@dataclass
class ArrivalRecord:
    train_id: str
    line: str
    station: str
    direction: str          # "Wolfratshausen" | "München Ost" | unknown
    scheduled_time: str     # ISO8601 UTC
    actual_time: str | None # ISO8601 UTC, None if cancelled
    delay_minutes: int | None
    cancelled: bool
    reason: str | None


def _parse_db_time(raw: str) -> datetime:
    """DB time format: YYMMDDHHMM → UTC datetime (DB times are local DE, treat as UTC for simplicity)."""
    return datetime.strptime(raw, "%y%m%d%H%M").replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _last_stop(path: str) -> str:
    """Extract final station from pipe-separated path string."""
    parts = [p.strip() for p in path.split("|") if p.strip()]
    return parts[-1] if parts else "unbekannt"


def parse_timetable(
    plan_xml: etree._Element,
    changes_xml: etree._Element,
    station: str = "Baierbrunn",
) -> list[ArrivalRecord]:
    """Merge plan + changes into ArrivalRecord list."""
    # Build changes index keyed by stop id
    change_index: dict[str, etree._Element] = {}
    for s in changes_xml.findall(".//s"):
        sid = s.get("id")
        if sid:
            change_index[sid] = s

    records: list[ArrivalRecord] = []

    for stop in plan_xml.findall(".//s"):
        sid = stop.get("id", "")
        tl = stop.find("tl")
        if tl is None:
            continue

        line_type = tl.get("c", "")
        line_num = tl.get("n", "")
        line = f"{line_type}{line_num}" if line_type else line_num

        # Only track S7
        if not line.startswith("S7") and tl.get("f") != "S":
            line_f = tl.get("f", "")
            if line_f != "S":
                continue

        ar = stop.find("ar")
        if ar is None:
            continue  # departure-only stop, skip

        pt_raw = ar.get("pt")
        if not pt_raw:
            continue

        scheduled_dt = _parse_db_time(pt_raw)

        # Direction from planned path of arrival (where it came from) or departure path (where it goes)
        dp = stop.find("dp")
        direction = "unbekannt"
        if dp is not None:
            ppth = dp.get("ppth", "")
            direction = _last_stop(ppth) if ppth else direction
        if direction == "unbekannt" and ar is not None:
            ppth = ar.get("ppth", "")
            if ppth:
                parts = [p.strip() for p in ppth.split("|") if p.strip()]
                direction = parts[0] if parts else direction

        cancelled = False
        actual_dt: datetime | None = None
        reason: str | None = None

        change_stop = change_index.get(sid)
        if change_stop is not None:
            car = change_stop.find("ar")
            if car is not None:
                cs = car.get("cs", "")
                cancelled = cs == "c"
                ct_raw = car.get("ct")
                if ct_raw and not cancelled:
                    actual_dt = _parse_db_time(ct_raw)
                reason = car.get("m") or car.get("msc")  # message / message code

        delay_minutes: int | None = None
        if not cancelled and actual_dt is not None:
            delta = actual_dt - scheduled_dt
            delay_minutes = int(delta.total_seconds() / 60)
        elif not cancelled:
            delay_minutes = 0
            actual_dt = scheduled_dt

        records.append(ArrivalRecord(
            train_id=sid,
            line=f"S{tl.get('n', '?')}" if tl.get("f") == "S" else line,
            station=station,
            direction=direction,
            scheduled_time=_iso(scheduled_dt),
            actual_time=_iso(actual_dt),
            delay_minutes=delay_minutes,
            cancelled=cancelled,
            reason=reason,
        ))

    return records

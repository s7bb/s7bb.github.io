"""Parse DB Timetables XML into ArrivalRecord dataclasses."""

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from lxml import etree

_DE_TZ = ZoneInfo("Europe/Berlin")


@dataclass
class ArrivalRecord:
    train_id: str
    line: str
    station: str
    direction: str           # raw terminus from DB API
    direction_bucket: str    # "muenchen" | "wolfratshausen" | "unknown"
    scheduled_time: str      # ISO8601 UTC
    actual_time: str | None  # ISO8601 UTC, None if cancelled
    delay_minutes: int | None
    cancelled: bool
    reason: str | None
    train_number: str | None = None


def _parse_db_time(raw: str) -> datetime:
    """DB time format: YYMMDDHHMM (Europe/Berlin local) → UTC datetime."""
    local = datetime.strptime(raw, "%y%m%d%H%M").replace(tzinfo=_DE_TZ)
    return local.astimezone(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _last_stop(path: str) -> str:
    """Extract final station from pipe-separated path string."""
    parts = [p.strip() for p in path.split("|") if p.strip()]
    return parts[-1] if parts else "unbekannt"


def classify_direction(dp_ppth: str) -> str:
    """Classify departure path into direction bucket.

    S7 (since 2024 timetable split) runs Wolfratshausen <-> München Hbf Gl.27-36.

    Returns "wolfratshausen", "muenchen", or "unknown".
    """
    if not dp_ppth:
        return "unknown"
    terminus = _last_stop(dp_ppth)
    if terminus == "Wolfratshausen":
        return "wolfratshausen"
    if "München" in terminus:
        return "muenchen"
    return "unknown"


def parse_timetable(
    plan_xml: etree._Element,
    changes_xml: etree._Element,
    station: str = "Baierbrunn",
) -> list[ArrivalRecord]:
    """Merge plan + changes into ArrivalRecord list."""
    change_index: dict[str, etree._Element] = {}
    for s in changes_xml.findall(".//s"):
        sid = s.get("id")
        if sid:
            change_index[sid] = s

    records: list[ArrivalRecord] = []

    for stop in plan_xml.findall(".//s"):
        sid = stop.get("id", "")

        dp = stop.find("dp")
        if dp is None:
            continue  # terminus / arrival-only stop, skip (no public departure time)

        line = (dp.get("l") or "").strip()
        ar = stop.find("ar")
        if line != "S7" and (ar is None or (ar.get("l") or "").strip() != "S7"):
            continue

        pt_raw = dp.get("pt")
        if not pt_raw:
            continue

        tl = stop.find("tl")
        n = tl.get("n") if tl is not None else None
        train_number = n.strip() if n and n.strip() else None

        scheduled_dt = _parse_db_time(pt_raw)

        dp_ppth = dp.get("ppth", "")
        direction = _last_stop(dp_ppth) if dp_ppth else "unbekannt"
        if direction == "unbekannt" and ar is not None:
            ppth = ar.get("ppth", "")
            if ppth:
                parts = [p.strip() for p in ppth.split("|") if p.strip()]
                direction = parts[0] if parts else direction

        direction_bucket = classify_direction(dp_ppth)

        cancelled = False
        actual_dt: datetime | None = None
        reason: str | None = None

        change_stop = change_index.get(sid)
        if change_stop is not None:
            cdp = change_stop.find("dp")
            car = change_stop.find("ar")
            # Cancellation: either ar or dp can carry cs="c"
            if (cdp is not None and cdp.get("cs", "") == "c") or (
                car is not None and car.get("cs", "") == "c"
            ):
                cancelled = True
            ct_raw = cdp.get("ct") if cdp is not None else None
            if ct_raw and not cancelled:
                actual_dt = _parse_db_time(ct_raw)
            if cdp is not None:
                reason = cdp.get("m") or cdp.get("msc")
            if reason is None and car is not None:
                reason = car.get("m") or car.get("msc")

        delay_minutes: int | None = None
        if not cancelled and actual_dt is not None:
            delta = actual_dt - scheduled_dt
            delay_minutes = int(delta.total_seconds() / 60)
        elif not cancelled:
            delay_minutes = 0
            actual_dt = scheduled_dt

        records.append(ArrivalRecord(
            train_id=sid,
            line="S7",
            station=station,
            direction=direction,
            direction_bucket=direction_bucket,
            scheduled_time=_iso(scheduled_dt),
            actual_time=_iso(actual_dt),
            delay_minutes=delay_minutes,
            cancelled=cancelled,
            reason=reason,
            train_number=train_number,
        ))

    return records

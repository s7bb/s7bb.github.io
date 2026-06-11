"""Parse DB Timetables XML into ArrivalRecord dataclasses."""

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from lxml import etree

_DE_TZ = ZoneInfo("Europe/Berlin")

# DB Timetables re-labels S7-Süd trains as "S5" while the Munich
# Stammstrecke is closed for construction. Both labels denote the
# same Baierbrunn S-Bahn service for our purposes.
_ACCEPTED_LINES = {"S7", "S5"}


@dataclass
class Disruption:
    category: str | None = None       # HIM category, e.g. "Störung"
    cause_code: int | None = None     # DB delay-cause code, e.g. 34
    window_from: str | None = None    # ISO8601 UTC
    window_to: str | None = None      # ISO8601 UTC


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
    dp_ppth: str = ""        # pipe-separated path Baierbrunn → terminus
    disruption: "Disruption | None" = None


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

    Normal S7 runs Wolfratshausen <-> München Hbf Gl.27-36. During Munich
    Stammstrecke construction the southbound train is relabelled S5 and
    the route is stitched onto S7-Nord so the public path becomes
    Wolfratshausen → München (tief, via Stammstrecke) → Kreuzstraße /
    Aying. Terminus alone is therefore not enough to identify Munich-
    direction trains; "München" can appear mid-path while the listed
    terminus is well east of the city.

    Returns "wolfratshausen", "muenchen", or "unknown".
    """
    if not dp_ppth:
        return "unknown"
    terminus = _last_stop(dp_ppth)
    if terminus == "Wolfratshausen":
        return "wolfratshausen"
    if "München" in dp_ppth:
        return "muenchen"
    return "unknown"


def _safe_db_time(raw: str | None) -> str | None:
    """Parse a DB YYMMDDHHMM bound to ISO UTC, or None if absent/malformed."""
    if not raw:
        return None
    try:
        return _iso(_parse_db_time(raw))
    except ValueError:
        return None


def extract_disruption(change_stop: etree._Element) -> "Disruption | None":
    """Build a Disruption from an <s> change element, or None if no usable
    message exists. Category + window come from the trip-level <m t="h">
    (direct child of <s>); cause_code from the first non-zero stop-level
    <m t="d"> on <ar> then <dp> (fixed scan order for determinism)."""
    category: str | None = None
    window_from: str | None = None
    window_to: str | None = None

    him = change_stop.find("m[@t='h']")
    if him is not None:
        category = him.get("cat")
        window_from = _safe_db_time(him.get("from"))
        window_to = _safe_db_time(him.get("to"))

    cause_code: int | None = None
    for parent_tag in ("ar", "dp"):           # ar first, then dp (deterministic)
        parent = change_stop.find(parent_tag)
        if parent is None:
            continue
        for m in parent.findall("m[@t='d']"):
            raw = m.get("c")
            if raw and raw != "0":
                try:
                    cause_code = int(raw)
                except ValueError:
                    continue
                break
        if cause_code is not None:
            break

    if category is None and cause_code is None:
        return None
    return Disruption(
        category=category,
        cause_code=cause_code,
        window_from=window_from,
        window_to=window_to,
    )


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
        ar_line = (ar.get("l") or "").strip() if ar is not None else ""
        # Accept S7 (normal) and S5 (substitute label DB applies to S7-Süd
        # services when the Munich Stammstrecke is closed for construction).
        if line not in _ACCEPTED_LINES and ar_line not in _ACCEPTED_LINES:
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
        disruption: Disruption | None = None

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
            disruption = extract_disruption(change_stop)

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
            dp_ppth=dp_ppth,
            disruption=disruption,
        ))

    return records

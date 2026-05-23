"""Terminus arrival tracking for S7 trains departing Baierbrunn.

After each Baierbrunn fetch cycle, classify every pending train as
arrived / short_turn / cancelled / pending by polling the terminus
station's /fchg feed and matching on the trip-id prefix carried in
``<s id>`` (the last ``-NN`` segment is the per-station stop sequence
and differs between Baierbrunn and the terminus; the prefix is stable
across stations for a single trip).

Why not match on ``<tl n>`` (the human-readable train number)? S-Bahn
entries in ``/fchg`` responses omit the ``<tl>`` element entirely — only
long-distance categories (ICE, ECE, RB, ...) carry it. Matching on
``tl/@n`` therefore drops every S-Bahn trip on the floor.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from lxml import etree

log = logging.getLogger(__name__)

_DB_TIME_FMT = "%y%m%d%H%M"  # planning/change times: Europe/Berlin local
_DE_TZ = ZoneInfo("Europe/Berlin")

# S-Bahn surface platforms 27-36 at München Hbf are a separate station
# in the Timetables API from the long-distance München Hbf (8000261).
MUENCHEN_HBF_EVA = "8098261"
WOLFRATSHAUSEN_EVA = "8006550"

# Per-direction average travel time Baierbrunn → terminus (minutes).
TRAVEL_TIME_MINUTES = {
    "muenchen":       35,
    "wolfratshausen": 20,
}
# Grace period beyond planned terminus arrival before declaring a missing train cancelled.
CUTOFF_GRACE_MINUTES = 60

# Resolved 2026-05-22 against DB Timetables /station/{name}. Stations along
# the two S7 directions, ordered Baierbrunn → terminus.
STATION_NAME_TO_EVA = {
    # Direction München
    "Buchenhain":                  "8071272",
    "Höllriegelskreuth":           "8002899",
    "Pullach":                     "8004899",
    "Großhesselohe Isartalbf":     "8002422",
    "München-Solln":               "8004161",
    "München Siemenswerke":        "8004137",
    "München-Mittersendling":      "8004154",
    "München Harras":              "8004130",
    "München Heimeranplatz":       "8005419",
    "München Donnersbergerbrücke": "8004128",
    "München Hbf Gl.27-36":        MUENCHEN_HBF_EVA,
    # Direction Wolfratshausen
    "Hohenschäftlarn":             "8002955",
    "Ebenhausen-Schäftlarn":       "8001621",
    "Icking":                      "8003039",
    "Wolfratshausen":              WOLFRATSHAUSEN_EVA,
}

TERMINUS_EVA_FOR_BUCKET = {
    "muenchen":       MUENCHEN_HBF_EVA,
    "wolfratshausen": WOLFRATSHAUSEN_EVA,
}


@dataclass(frozen=True)
class PendingTrain:
    train_id: str         # Baierbrunn s/@id; trip prefix is rsplit('-',1)[0]
    scheduled_time: str   # ISO UTC
    direction_bucket: str
    dp_ppth: str          # may be empty/None for legacy rows


@dataclass(frozen=True)
class TerminusUpdate:
    train_id: str
    scheduled_time: str
    terminus_status: str                    # "arrived" | "short_turn" | "cancelled"
    terminus_delay_minutes: int | None
    terminus_short_turn_station: str | None


def trip_prefix(sid: str) -> str:
    """Return the cross-station trip key for a DB Timetables ``s/@id``.

    ``s/@id`` has the form ``<trip>-<YYMMDDHHMM>-<stop_seq>``; the stop
    sequence varies per station, the rest is constant for a trip. An
    empty/invalid id yields an empty string (caller skips empties).
    """
    if not sid:
        return ""
    head, sep, _tail = sid.rpartition("-")
    return head if sep else ""


def build_index(feed: etree._Element) -> dict[str, etree._Element]:
    """Index a /fchg response by trip-prefix.

    Entries without a usable id are skipped — the prefix is the only
    cross-station join key available for S-Bahn trips (``<tl>`` is absent).
    """
    out: dict[str, etree._Element] = {}
    for s in feed.findall(".//s"):
        key = trip_prefix(s.get("id") or "")
        if key:
            out[key] = s
    return out


def _build_plan_pt_index(plan_xml: etree._Element) -> dict[str, str]:
    """Index a /plan response by trip-prefix → planned arrival time.

    /plan carries the authoritative ``ar/@pt`` for every regular run,
    which /fchg omits for S-Bahn. Used to compute real arrival delay.
    Values are the raw DB time string ``YYMMDDHHMM`` (Europe/Berlin).
    """
    out: dict[str, str] = {}
    for s in plan_xml.findall(".//s"):
        key = trip_prefix(s.get("id") or "")
        if not key:
            continue
        ar = s.find("ar")
        if ar is None:
            continue
        pt = ar.get("pt")
        if pt:
            out[key] = pt
    return out


def _is_cancelled(entry: etree._Element) -> bool:
    """True iff this station's <ar> (or <dp> fallback) carries cs="c"."""
    ar = entry.find("ar")
    if ar is not None and ar.get("cs", "") == "c":
        return True
    dp = entry.find("dp")
    if dp is not None and dp.get("cs", "") == "c":
        return True
    return False


def _parse_db_time(raw: str) -> datetime:
    local = datetime.strptime(raw, _DB_TIME_FMT).replace(tzinfo=_DE_TZ)
    return local.astimezone(UTC)


def _cutoff(pending: PendingTrain) -> datetime:
    sched = datetime.fromisoformat(pending.scheduled_time)
    travel = TRAVEL_TIME_MINUTES.get(pending.direction_bucket, 35)
    return sched + timedelta(minutes=travel + CUTOFF_GRACE_MINUTES)


def _arrival_delay_minutes(entry: etree._Element) -> int:
    """Compute ct - pt in whole minutes; 0 if ct missing.

    /fchg ``<ar>`` carries ``ct`` (changed time) when the arrival deviates
    from plan. Planned time ``pt`` is not always echoed in /fchg — when
    missing, fall back to the row's scheduled time (passed by caller).
    """
    ar = entry.find("ar")
    if ar is None:
        return 0
    pt = ar.get("pt")
    ct = ar.get("ct")
    if not ct:
        return 0
    if not pt:
        return 0  # planned time unknown from /fchg alone
    delta = _parse_db_time(ct) - _parse_db_time(pt)
    return int(delta.total_seconds() / 60)


def classify(
    pending: PendingTrain,
    entry: etree._Element | None,
    now: datetime,
    drilldown,
) -> TerminusUpdate | None:
    """Classify a single pending train.

    Returns a TerminusUpdate to write, or None to leave the row pending.

    `drilldown` is a callable `(dp_ppth, train_id) -> str | None` that
    returns the Baierbrunn-most station where the train is reported with
    cs="c", or None if no cancellation point is found.
    """
    # Case A: terminus feed has an entry for this trip.
    if entry is not None:
        if _is_cancelled(entry):
            station = drilldown(pending.dp_ppth, pending.train_id)
            if station is None:
                return TerminusUpdate(
                    pending.train_id, pending.scheduled_time,
                    terminus_status="cancelled",
                    terminus_delay_minutes=None,
                    terminus_short_turn_station=None,
                )
            return TerminusUpdate(
                pending.train_id, pending.scheduled_time,
                terminus_status="short_turn",
                terminus_delay_minutes=None,
                terminus_short_turn_station=station,
            )
        # Not cancelled at terminus → arrived (possibly late).
        return TerminusUpdate(
            pending.train_id, pending.scheduled_time,
            terminus_status="arrived",
            terminus_delay_minutes=_arrival_delay_minutes(entry),
            terminus_short_turn_station=None,
        )

    # Case B: missing from terminus feed.
    if now <= _cutoff(pending):
        return None  # stay pending; next cycle may catch it

    # Case C: missing past cutoff → drilldown.
    station = drilldown(pending.dp_ppth, pending.train_id)
    if station is None:
        return TerminusUpdate(
            pending.train_id, pending.scheduled_time,
            terminus_status="cancelled",
            terminus_delay_minutes=None,
            terminus_short_turn_station=None,
        )
    return TerminusUpdate(
        pending.train_id, pending.scheduled_time,
        terminus_status="short_turn",
        terminus_delay_minutes=None,
        terminus_short_turn_station=station,
    )


def list_pending_trains(
    conn: sqlite3.Connection, now: datetime
) -> list[PendingTrain]:
    """Return Baierbrunn rows still awaiting terminus classification.

    Window: [now - 2h, now + 5min]. Older trains are written off (next
    cycle won't classify them — terminus feed has rolled past); +5min lets
    early-departing trains that are seconds ahead of the clock still match.
    """
    lo = (now - timedelta(hours=2)).isoformat()
    hi = (now + timedelta(minutes=5)).isoformat()
    cur = conn.execute(
        """
        SELECT train_id, scheduled_time, direction_bucket, dp_ppth
          FROM arrivals
         WHERE terminus_status = 'pending'
           AND cancelled = 0
           AND scheduled_time BETWEEN ? AND ?
        """,
        (lo, hi),
    )
    return [
        PendingTrain(
            train_id=row[0],
            scheduled_time=row[1],
            direction_bucket=row[2],
            dp_ppth=row[3] or "",
        )
        for row in cur.fetchall()
    ]


ZERO_MATCH_WARN_THRESHOLD = 3


def _record_health(
    conn: sqlite3.Connection, eva: str, *, pending_count: int, match_count: int, now: datetime
) -> None:
    """Increment/reset zero-match streak per terminus EVA."""
    if pending_count == 0:
        return  # quiet cycle isn't evidence of mismatch
    if match_count > 0:
        conn.execute(
            """
            INSERT INTO terminus_health (eva, zero_match_streak, updated_at)
            VALUES (?, 0, ?)
            ON CONFLICT(eva) DO UPDATE SET zero_match_streak=0, updated_at=excluded.updated_at
            """,
            (eva, now.isoformat()),
        )
        conn.commit()
        return
    cur = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE eva=?", (eva,)
    ).fetchone()
    streak = (cur[0] if cur else 0) + 1
    conn.execute(
        """
        INSERT INTO terminus_health (eva, zero_match_streak, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(eva) DO UPDATE SET
            zero_match_streak = excluded.zero_match_streak,
            updated_at = excluded.updated_at
        """,
        (eva, streak, now.isoformat()),
    )
    conn.commit()
    if streak >= ZERO_MATCH_WARN_THRESHOLD:
        log.warning(
            "terminus: 0 matches against eva=%s across %d pending trains for %d consecutive cycles "
            "— possible EVA mismatch",
            eva, pending_count, streak,
        )


def update_terminus_for_window(
    conn: sqlite3.Connection,
    client,
    now: datetime | None = None,
) -> int:
    """Orchestrator: poll terminus feeds, classify pending trains, persist.

    `client` is duck-typed: must expose `fetch_full_changes(eva) -> Element`.
    Returns count of rows actually updated.

    Caller (service.py) wraps this in try/except — a raise here must not
    abort the parent fetch cycle.
    """
    from .storage import update_terminus_fields  # local import: cycle break

    now = now or datetime.now(UTC)
    pending = list_pending_trains(conn, now)
    if not pending:
        return 0

    # Group by direction so we hit each terminus /fchg at most once.
    by_bucket: dict[str, list[PendingTrain]] = {}
    for p in pending:
        by_bucket.setdefault(p.direction_bucket, []).append(p)

    def _drilldown(dp_ppth, train_id):
        return drilldown_short_turn(client, dp_ppth, train_id)

    updates: list[dict] = []
    for bucket, group in by_bucket.items():
        eva = TERMINUS_EVA_FOR_BUCKET.get(bucket)
        if eva is None:
            continue  # 'unknown' bucket — never resolvable
        try:
            feed = client.fetch_full_changes(eva)
        except Exception:
            log.exception("terminus: /fchg %s failed; %d pending stay pending", eva, len(group))
            continue
        idx = build_index(feed)
        match_count = 0
        for p in group:
            entry = idx.get(trip_prefix(p.train_id))
            if entry is not None:
                match_count += 1
            update = classify(p, entry, now, drilldown=_drilldown)
            if update is not None:
                updates.append({
                    "train_id": update.train_id,
                    "scheduled_time": update.scheduled_time,
                    "terminus_status": update.terminus_status,
                    "terminus_delay_minutes": update.terminus_delay_minutes,
                    "terminus_short_turn_station": update.terminus_short_turn_station,
                })
        _record_health(conn, eva, pending_count=len(group),
                       match_count=match_count, now=now)

    if not updates:
        return 0
    return update_terminus_fields(conn, updates)


def drilldown_short_turn(client, dp_ppth: str | None, train_id: str) -> str | None:
    """Walk dp.ppth reverse from one-before-terminus toward Baierbrunn,
    looking up each station's /fchg and returning the Baierbrunn-most
    station where the train is reported with cs='c'.

    The /fchg endpoint only returns entries for stations where something
    *changed*. So `entry is None` at an intermediate means the train passed
    on time there — i.e. we walked past the cancellation point and can stop.

    Returns None if no cancellation point is reachable (train vanished
    before any station that reported a change, or HTTP failure mid-walk,
    or dp_ppth is empty/None).
    """
    if not dp_ppth:
        return None
    prefix = trip_prefix(train_id)
    if not prefix:
        return None
    parts = [p for p in dp_ppth.split("|") if p]
    # parts[-1] is terminus; walk everything before it, reverse
    candidate: str | None = None
    for name in reversed(parts[:-1]):
        eva = STATION_NAME_TO_EVA.get(name)
        if eva is None:
            log.warning("terminus drilldown: unknown intermediate %s", name)
            continue
        try:
            feed = client.fetch_full_changes(eva)
        except Exception:
            log.exception("terminus drilldown: /fchg %s failed; aborting walk", eva)
            return candidate  # best-effort: return what we have so far
        entry = build_index(feed).get(prefix)
        if entry is None:
            # No change at this station → train passed → past cancellation point.
            break
        if _is_cancelled(entry):
            candidate = name  # keep walking; may find a Baierbrunn-er hit
            continue
        # Entry present but not cancelled (delay only) → train ran here → stop.
        break
    return candidate

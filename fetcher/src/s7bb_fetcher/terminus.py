"""Terminus arrival tracking for S7 trains departing Baierbrunn.

After each Baierbrunn fetch cycle, classify every pending train as
arrived / short_turn / cancelled / pending by polling the terminus
station's /fchg feed and matching on train_number.
"""

import logging
import sqlite3  # noqa: F401
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta  # noqa: F401
from zoneinfo import ZoneInfo

from lxml import etree

log = logging.getLogger(__name__)

_DB_TIME_FMT = "%y%m%d%H%M"  # planning/change times: Europe/Berlin local
_DE_TZ = ZoneInfo("Europe/Berlin")

MUENCHEN_HBF_EVA = "8000261"
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
    train_number: str
    scheduled_time: str   # ISO UTC
    direction_bucket: str
    dp_ppth: str          # may be empty/None for legacy rows


@dataclass(frozen=True)
class TerminusUpdate:
    train_number: str
    scheduled_time: str
    terminus_status: str                    # "arrived" | "short_turn" | "cancelled"
    terminus_delay_minutes: int | None
    terminus_short_turn_station: str | None


def build_index(feed: etree._Element) -> dict[str, etree._Element]:
    """Index a /fchg response by train_number."""
    out: dict[str, etree._Element] = {}
    for s in feed.findall(".//s"):
        tl = s.find("tl")
        n = tl.get("n") if tl is not None else None
        if n and n.strip():
            out[n.strip()] = s
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

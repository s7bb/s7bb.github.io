"""DB Timetables API HTTP client."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from lxml import etree

BASE_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
BAIERBRUNN_EVA = "8004073"
_DE_TZ = ZoneInfo("Europe/Berlin")


def _session() -> requests.Session:
    api_key = os.environ["DB_API_KEY"]
    s = requests.Session()
    s.headers.update({
        "DB-Api-Key": api_key,
        "DB-Client-Id": os.environ.get("DB_CLIENT_ID", ""),
        "Accept": "application/xml",
    })
    return s


def fetch_plan(eva: str, date: str, hour: str) -> etree._Element:
    """Fetch planned timetable. date=YYMMDD, hour=HH."""
    url = f"{BASE_URL}/plan/{eva}/{date}/{hour}"
    resp = _session().get(url, timeout=10)
    resp.raise_for_status()
    return etree.fromstring(resp.content)


def fetch_full_changes(eva: str) -> etree._Element:
    """Fetch full changes (actual vs planned) for a station."""
    url = f"{BASE_URL}/fchg/{eva}"
    resp = _session().get(url, timeout=10)
    resp.raise_for_status()
    return etree.fromstring(resp.content)


def fetch_recent_changes(eva: str) -> etree._Element:
    """Fetch only changes in the last 2 minutes."""
    url = f"{BASE_URL}/rchg/{eva}"
    resp = _session().get(url, timeout=10)
    resp.raise_for_status()
    return etree.fromstring(resp.content)


def fetch_baierbrunn_now() -> tuple[etree._Element, etree._Element]:
    """Return (plan_xml, changes_xml) for Baierbrunn at current Europe/Berlin hour."""
    now = datetime.now(tz=_DE_TZ)
    date = now.strftime("%y%m%d")
    hour = now.strftime("%H")
    plan = fetch_plan(BAIERBRUNN_EVA, date, hour)
    changes = fetch_full_changes(BAIERBRUNN_EVA)
    return plan, changes

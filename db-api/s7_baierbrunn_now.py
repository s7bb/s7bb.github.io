#!/usr/bin/env python3
"""Print current S7 arrivals at Baierbrunn.

Reads credentials from sibling files `client_id` and `client_secret`. Fetches
the planned timetable for the current Europe/Berlin hour plus the full-changes
feed, then prints scheduled time, actual time, delay, direction, and platform
for every S7 stop.

Run:
    python3 db-api/s7_baierbrunn_now.py
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

BASE_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
EVA_BAIERBRUNN = os.environ.get("S7BB_EVA", "8000781")
DE_TZ = ZoneInfo("Europe/Berlin")
HERE = Path(__file__).resolve().parent

def _read_secret(name: str) -> str:
    path = HERE / name
    if not path.is_file():
        sys.exit(f"missing credential file: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        sys.exit(f"empty credential file: {path}")
    return value


def _get(url: str, client_id: str, api_key: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "DB-Client-Id": client_id,
            "DB-Api-Key": api_key,
            "Accept": "application/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        sys.exit(f"GET {url} -> HTTP {exc.code}\n{body}")
    except urllib.error.URLError as exc:
        sys.exit(f"GET {url} failed: {exc.reason}")


def _fmt_time(raw: str) -> str:
    """YYMMDDHHMM -> HH:MM (DE local)."""
    if not raw:
        return "--:--"
    return f"{raw[6:8]}:{raw[8:10]}"


def _last_stop(path: str) -> str:
    parts = [p.strip() for p in path.split("|") if p.strip()]
    return parts[-1] if parts else ""


def _direction_bucket(dp_ppth: str) -> str:
    """S7 runs Wolfratshausen <-> München Hbf Gl.27-36 (since 2024 split)."""
    if not dp_ppth:
        return "?"
    terminus = _last_stop(dp_ppth)
    if terminus == "Wolfratshausen":
        return "→ Wolfratshausen"
    if "München" in terminus:
        return "→ München Hbf"
    return f"→ {terminus}"


def _delay_minutes(pt: str, ct: str) -> int:
    p = datetime.strptime(pt, "%y%m%d%H%M")
    c = datetime.strptime(ct, "%y%m%d%H%M")
    return int((c - p).total_seconds() // 60)


def main() -> int:
    client_id = _read_secret("client_id")
    api_key = _read_secret("client_secret")

    now = datetime.now(tz=DE_TZ)
    date = now.strftime("%y%m%d")
    hour = now.strftime("%H")

    plan_url = f"{BASE_URL}/plan/{EVA_BAIERBRUNN}/{date}/{hour}"
    fchg_url = f"{BASE_URL}/fchg/{EVA_BAIERBRUNN}"

    print(f"Baierbrunn (EVA {EVA_BAIERBRUNN}) — {now.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"Planhour: {date}/{hour}\n")

    plan_root = ET.fromstring(_get(plan_url, client_id, api_key))
    fchg_root = ET.fromstring(_get(fchg_url, client_id, api_key))

    changes: dict[str, ET.Element] = {}
    for s in fchg_root.findall("s"):
        sid = s.get("id")
        if sid:
            changes[sid] = s

    rows = []
    for s in plan_root.findall("s"):
        ar = s.find("ar")
        if ar is None:
            continue
        if (ar.get("l") or "").strip() != "S7":
            continue

        sid = s.get("id", "")
        pt = ar.get("pt", "")
        platform = ar.get("pp", "")
        from_path = ar.get("ppth", "")
        from_stop = _last_stop(from_path) or "?"

        dp = s.find("dp")
        dp_ppth = dp.get("ppth", "") if dp is not None else ""
        direction = _direction_bucket(dp_ppth)

        actual = "on time"
        cancelled = False
        ct = ""
        change_stop = changes.get(sid)
        if change_stop is not None:
            car = change_stop.find("ar")
            if car is not None:
                if car.get("cs") == "c":
                    cancelled = True
                    actual = "CANCELLED"
                else:
                    ct = car.get("ct", "")
                    if ct:
                        d = _delay_minutes(pt, ct)
                        actual = f"+{d} min" if d > 0 else ("on time" if d == 0 else f"{d} min")

        rows.append({
            "pt": pt, "ct": ct, "platform": platform,
            "from": from_stop, "direction": direction,
            "status": actual, "cancelled": cancelled,
        })

    if not rows:
        print("no S7 arrivals in this hour window")
        return 0

    rows.sort(key=lambda r: r["pt"])
    print(f"{'Plan':<6} {'Ist':<6} {'Pl':<3} {'Richtung':<20} {'Von':<25} Status")
    print("-" * 80)
    for r in rows:
        print(
            f"{_fmt_time(r['pt']):<6} {_fmt_time(r['ct']):<6} "
            f"{r['platform']:<3} {r['direction']:<20} {r['from']:<25} {r['status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

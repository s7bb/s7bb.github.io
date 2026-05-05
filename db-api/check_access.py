#!/usr/bin/env python3
"""Smoke test for DB Timetables API access.

Reads credentials from sibling files `client_id` and `client_secret` and
fetches the current planned hour for Baierbrunn (EVA from $S7BB_EVA, default 8000781) plus the
full-changes feed. Prints HTTP status, response size, and the S7 arrivals
parsed from the plan XML.

Run:
    python3 db-api/check_access.py
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
            print(f"GET {url} -> HTTP {resp.status}")
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        sys.exit(f"GET {url} -> HTTP {exc.code}\n{body}")
    except urllib.error.URLError as exc:
        sys.exit(f"GET {url} failed: {exc.reason}")


def _print_s7_arrivals(plan_xml: bytes) -> None:
    root = ET.fromstring(plan_xml)
    rows = []
    for s in root.findall("s"):
        ar = s.find("ar")
        if ar is None:
            continue
        line = (ar.get("l") or "").strip()
        if line != "S7":
            continue
        ppth = ar.get("ppth", "")
        rows.append({
            "time": ar.get("pt", ""),
            "line": line,
            "from": ppth.split("|")[-1] if ppth else "",
            "platform": ar.get("pp", ""),
        })
    if not rows:
        print("no S7 arrivals in this hour window (off-peak or empty plan)")
        return
    print(f"S7 arrivals in current hour: {len(rows)}")
    for r in rows:
        print(f"  {r['time']}  S7  from {r['from']:<25}  pl {r['platform']}")


def main() -> int:
    client_id = _read_secret("client_id")
    api_key = _read_secret("client_secret")

    now = datetime.now(tz=DE_TZ)
    date = now.strftime("%y%m%d")
    hour = now.strftime("%H")

    plan_url = f"{BASE_URL}/plan/{EVA_BAIERBRUNN}/{date}/{hour}"
    fchg_url = f"{BASE_URL}/fchg/{EVA_BAIERBRUNN}"

    print(f"Time (DE): {now.isoformat(timespec='seconds')}")
    print(f"Station EVA: {EVA_BAIERBRUNN} (Baierbrunn)\n")

    plan_xml = _get(plan_url, client_id, api_key)
    print(f"  plan bytes: {len(plan_xml)}")
    _print_s7_arrivals(plan_xml)

    print()
    fchg_xml = _get(fchg_url, client_id, api_key)
    print(f"  fchg bytes: {len(fchg_xml)}")
    fchg_root = ET.fromstring(fchg_xml)
    print(f"  fchg <s> elements: {len(fchg_root.findall('s'))}")

    print("\nOK: API reachable, credentials valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

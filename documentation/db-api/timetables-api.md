# DB Timetables API v1 - Reference

Source pages:
- https://developers.deutschebahn.com/db-api-marketplace/apis/product/timetables
- https://developers.deutschebahn.com/db-api-marketplace/apis/node/160163
Retrieved: 2026-05-05

---

## Overview

The Timetables API provides arrival and departure information for stations operated by DB Station&Service AG, in the form of platform display (Gleistafeln) data and full journey details. It exposes both planned schedules and real-time changes (delays, cancellations).

| Property | Value |
|----------|-------|
| API name | Timetables |
| Version | 1.0.274 |
| Portal product node | `160160` (API) / `160163` (product) |
| Response format | XML |
| License | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| Contact | IRIS-TTS.API@deutschebahn.com |

---

## Authentication

### Required Headers

Every request must include both headers:

| Header | Description |
|--------|-------------|
| `DB-Api-Key` | Client Secret obtained from the DB API Marketplace application page |
| `DB-Client-Id` | Client ID obtained from the DB API Marketplace application page |

Both credentials are obtained by:
1. Creating an account at https://developers.deutschebahn.com
2. Creating an application in the portal (Client ID and API Key are generated on creation; the key is shown only once)
3. Subscribing to the Timetables product (free plan is sufficient)

Example:
```http
GET /db-api-marketplace/apis/timetables/v1/plan/8000781/260505/12 HTTP/1.1
Host: apis.deutschebahn.com
DB-Api-Key: <your-api-key>
DB-Client-Id: <your-client-id>
Accept: application/xml
```

### x509 Client Certificates

**Not required.** The Timetables API uses header-based authentication only (`DB-Api-Key` + `DB-Client-Id`). No x509 client certificate is needed at the TLS layer.

The portal login uses OAuth 2.0 with DB Kundenkonto as the identity provider. There are no certificate upload fields anywhere in the application creation or subscription flow.

### Accept Header

The API returns XML. Including `Accept: application/xml` is recommended for explicitness, though the API responds with XML regardless.

---

## Base URL

### Production

```
https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1
```

### Sandbox / Test Environment

No separate sandbox hostname is documented. The marketplace provides:
- A "Versuch es!" (Try it out!) tab within the portal UI for interactive testing
- The "Free" subscription plan for real production calls at no cost

---

## Endpoints

### GET /plan/{evaNo}/{date}/{hour}

Returns the **planned timetable** for a station for a given hour.

| Parameter | Location | Type | Format | Description |
|-----------|----------|------|--------|-------------|
| `evaNo` | path | string | numeric | EVA station number (e.g. `8000781` for Baierbrunn) |
| `date` | path | string | `YYMMDD` | Date in 2-digit year + month + day format |
| `hour` | path | string | `HH` | Hour in 24-hour format (00–23) |

Example:
```
GET https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/plan/8000781/260505/12
```

Returns all scheduled stops at Baierbrunn for the hour 12:00–12:59 on 2026-05-05.

Response: XML `<timetable>` element with `<s>` (stop) children.

---

### GET /fchg/{evaNo}

Returns the **full set of current changes** for a station - all deviations from plan currently known (delays, cancellations, platform changes). This is the complete snapshot, not incremental.

| Parameter | Location | Type | Format | Description |
|-----------|----------|------|--------|-------------|
| `evaNo` | path | string | numeric | EVA station number |

Example:
```
GET https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/fchg/8000781
```

Response: XML `<timetable>` element with `<s>` children, each containing changed `<ar>` (arrival) or `<dp>` (departure) sub-elements.

---

### GET /rchg/{evaNo}

Returns **only changes from the last ~2 minutes** for a station. A lighter-weight incremental endpoint for frequent polling.

| Parameter | Location | Type | Format | Description |
|-----------|----------|------|--------|-------------|
| `evaNo` | path | string | numeric | EVA station number |

Example:
```
GET https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/rchg/8000781
```

---

### GET /station/{pattern}

Station lookup by name pattern.

| Parameter | Location | Type | Description |
|-----------|----------|------|-------------|
| `pattern` | path | string | Station name search pattern |

Example:
```
GET https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/station/BLS
```

Note: Returns 401 without valid credentials.

---

## XML Response Format

### Plan response (`/plan` endpoint)

Root element: `<timetable station="{name}" eva="{evaNo}">`

Each stop is an `<s>` element with `id` attribute. Relevant children:

**`<tl>` - Train Line**

| Attribute | Description |
|-----------|-------------|
| `f` | Train category code (e.g. `S` for S-Bahn) |
| `t` | Trip type (e.g. `p` for planned) |
| `o` | Operator code |
| `c` | Class/category (e.g. `S`) |
| `n` | Line number (e.g. `7` for S7) |

**`<ar>` - Arrival**

| Attribute | Description |
|-----------|-------------|
| `pt` | Planned time, format `YYMMDDHHMM` (DE local time) |
| `pp` | Platform |
| `l` | Line number |
| `ppth` | Pipe-separated list of previous stops (origin path) |

**`<dp>` - Departure**

| Attribute | Description |
|-----------|-------------|
| `pt` | Planned departure time, format `YYMMDDHHMM` |
| `pp` | Platform |
| `l` | Line number |
| `ppth` | Pipe-separated list of upcoming stops (destination path) |

Example plan XML:
```xml
<timetable station="Baierbrunn" eva="8000781">
  <s id="trip-S7-001-2605051200">
    <tl f="S" t="p" o="800725" c="S" n="6761"/>
    <ar pt="2605051200" pp="2" l="S7"
        ppth="München Hbf Gl.27-36|...|Buchenhain"/>
    <dp pt="2605051201" pp="2" l="S7"
        ppth="Hohenschäftlarn|Ebenhausen-Schäftlarn|Icking|Wolfratshausen"/>
  </s>
</timetable>
```

### Changes response (`/fchg` and `/rchg` endpoints)

Root element: `<timetable station="{name}" eva="{evaNo}">`

Each `<s>` element is keyed by `id` matching the plan stop. Changed `<ar>` or `<dp>` elements contain:

| Attribute | Description |
|-----------|-------------|
| `ct` | Changed (actual) time, format `YYMMDDHHMM` |
| `cs` | Change status: `d` = delayed, `c` = cancelled |
| `m` | Delay reason message |
| `msc` | Machine-readable reason code |

Example changes XML (one delayed, one cancelled):
```xml
<timetable station="Baierbrunn" eva="8000781">
  <s id="trip-S7-001-2605051200">
    <ar ct="2605051207" cs="d"/>
  </s>
  <s id="trip-S7-003-2605051300">
    <ar cs="c"/>
  </s>
</timetable>
```

### Empty changes XML

When no changes exist:
```xml
<timetable station="Baierbrunn" eva="8000781"/>
```

---

## Time Format

DB Timetables uses `YYMMDDHHMM` (2-digit year + month + day + hour + minute) for all timestamps.

- **Timezone**: Times are in **German local time** (CET/CEST). The API does not use UTC.
- Example: `2605051207` = 2026-05-05 12:07 local time

In the S7BB fetcher, times are parsed with `datetime.strptime(raw, "%y%m%d%H%M")` and stored as UTC (with a simplification noted in code comments: DE local time is treated as UTC, acceptable for the relative delay calculations this project performs).

---

## Baierbrunn Station

| Property | Value |
|----------|-------|
| Station name | Baierbrunn |
| EVA number | `8000781` |
| Line | S7 (München ↔ Wolfratshausen) |

---

## Rate Limits

### Free Plan
- **60 calls per minute**
- 24/7 availability
- No SLA / service guarantee
- Cost: free

The S7BB fetcher calls:
- `/plan` once per fetch cycle (every 5 minutes) for the current hour
- `/fchg` once per fetch cycle for real-time changes

This is well within the 60 calls/minute limit.

---

## Usage in S7BB

The fetcher uses these two endpoints in combination:

```
fetch_plan(eva, YYMMDD, HH)   → GET /plan/{eva}/{date}/{hour}  → plan XML
fetch_full_changes(eva)        → GET /fchg/{eva}                → changes XML
```

These are merged in `parser.py`: the `<s id="...">` elements from the changes XML are keyed against those from the plan XML. Matched stops have their actual times and cancellation status applied; unmatched plan stops are treated as on-time.

Implementation: `/home/lima.guest/aiworkshop/s7bb/fetcher/src/s7bb_fetcher/api.py`

---

## Terms of Service

- Attribution to Deutsche Bahn AG required when data is incorporated into OpenStreetMap.
- DB Station&Service AG assumes no liability for completeness or accuracy of the data.
- Terms: http://www.bahnhof.de/bahnhof-de/nutzungsbedingungen_wbt.html

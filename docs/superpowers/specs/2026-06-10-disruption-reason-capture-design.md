# Disruption Reason Capture - Design

- **Date:** 2026-06-10
- **Status:** Approved (pending spec review)
- **Author:** brainstormed with Claude Code

## Problem

When an S7 train at Baierbrunn is disrupted (cancelled, delayed, or
short-turned), S7BB records no human-meaningful reason for it. The
`reason` field exists end to end (parser -> storage -> exporter ->
`latest.json`) but is effectively always `null`.

Root cause: `parser.py:138` reads `reason = cdp.get("m") or cdp.get("msc")`
- an **attribute** lookup on the `<dp>`/`<ar>` change elements. DB
Timetables does not put messages in attributes for S-Bahn services; it
puts them in child `<m>` elements. So the read returns `None` on every
S-Bahn trip and the reason is silently lost.

This surfaced while investigating a real Munich <-> Mittersendling
`Störung` on 2026-06-10 ~06:19-08:30 that cancelled/short-turned several
trains. The DB `/fchg` feed carried the full disruption (HIM message +
per-stop cause codes), but S7BB stored nothing about why.

### Concrete example (from live `/fchg`, Baierbrunn EVA 8000781)

```xml
<s id="-173999216413506416-2606100654-5" eva="8004154">
  <m id="r2635205" t="h" from="2606100619" to="2606100830" cat="Störung" pr="1"/>
  <ar cpth="" ct="2606100735" cs="c" l="S7">
    <m id="r59585930" t="d" c="34"/>
    <m id="r59586864" t="f" c="0"/>
  </ar>
  ...
</s>
```

Message-element survey across one Baierbrunn `/fchg` response:

- `t="h"` (trip-level, 3 seen): HIM message, carries `cat` ("Störung")
  and `from`/`to` window. The disruption category.
- `t="d"` (stop-level on `ar`/`dp`): delay-cause, carries numeric `c`
  code. Observed codes: 34, 43, 44, 48.
- `t="f"` (stop-level): all `c="0"` - noise, ignored.

## Goals

1. Fix the parser so disruption reason is actually captured.
2. Apply to **all** disrupted trains: cancelled, delayed, short-turned.
3. Store the **full** disruption detail in `latest.json` (and archive
   JSON) - this is the canonical, rich source of truth.
4. Render a **reduced**, mobile-friendly view in the web UI: a compact
   badge by default, full detail on tap (progressive disclosure).

## Non-goals (explicitly kept out of scope)

- **Gap #2 - origin-cut short-turn detection.** Trains whose *origin*
  was moved to a later station (e.g. a southbound run restarting at
  Mittersendling) are still not flagged as short-turns. Untouched.
- **Terminus classification of cancelled rows.** Cancelled-at-Baierbrunn
  trains still skip terminus classification (`terminus_status` stays
  `NULL`). This change adds a *reason*, not a terminus status, to those
  rows.
- Fetching free-text HIM message bodies (not present inline in `/fchg`;
  would require a separate message-catalogue call).

## Architecture / data flow

```
/fchg XML <m> elements
  -> parser.py        extract category + cause_code + window
  -> storage.py       4 new columns on `arrivals`
  -> exporter.py      assemble nested `disruption` object, decode code
  -> latest.json      FULL detail (canonical)
  -> web UI           reduced badge + tap-to-expand (thin projection)
```

Separation of concerns: **JSON is the rich source of truth; the UI is a
thin projection that picks only what fits a mobile screen.** UI verbosity
can change later without touching the data pipeline.

## Components

### 1. parser.py - fix extraction

Replace the attribute read at `parser.py:138-140` with a child `<m>`
walk. New helper, e.g. `extract_disruption(change_stop) -> Disruption | None`,
where `change_stop` is the `<s>` element (the same node already returned
by `change_index.get(sid)` and used for `.find("dp")`/`.find("ar")`).

**Element levels (do not confuse them).** The two `<m>` kinds live at
different depths in the `<s>` subtree:

- `<m t="h">` is a **direct child of `<s>`**, sibling to `<ar>`/`<dp>`
  (see the example XML above). Read it with `change_stop.find("m[@t='h']")`
  (or iterate `change_stop` direct children), **not** from inside
  `ar`/`dp`.
- `<m t="d">` / `<m t="f">` are **children of `<ar>` / `<dp>`**.

- **Category + window** from the trip-level `<m t="h">`:
  - `category` = `m.get("cat")` (e.g. "Störung").
  - `window_from` / `window_to` = parse `m.get("from")` / `m.get("to")`
    (DB-local `YYMMDDHHMM`, Europe/Berlin) -> UTC ISO. Reuse the
    existing `_parse_db_time` helper.
- **Cause code** from the stop-level `<m t="d">` on `ar`/`dp`:
  - `cause_code` = first `int(m.get("c"))` where `t="d"` and `c != "0"`.
  - **Scan order is fixed for determinism:** `<ar>` children first, then
    `<dp>` children; within each, document order; first non-`"0"` wins.
    (A train can carry `t="d"` codes on both `ar` and `dp`; without a
    fixed order the captured code would vary between refetches.)
  - Ignore `t="f"` and `c="0"`.
- Returns `None` when no `t="h"` and no usable `t="d"` code exist (the
  on-time path is unchanged).

The `ArrivalRecord` dataclass gains the fields (or a nested
`disruption` sub-object - implementer's choice, but keep it serialisable
for storage). The old `reason` field is **retained on the dataclass,
always `None`** (parser stops setting it) - see storage note below for
why it is not removed outright.

### 2. storage.py - schema + persistence

Add four columns to `arrivals` via the existing forward-migration
pattern (the idempotent `for col, ddl in (...)` ALTER loop at
`storage.py:54-65`):

- `disruption_category      TEXT`
- `disruption_cause_code     INTEGER`
- `disruption_window_from    TEXT`   (ISO UTC)
- `disruption_window_to      TEXT`   (ISO UTC)

Carry them through the `INSERT ... ON CONFLICT` upsert using
`COALESCE(excluded.x, x)` for all four columns - **once captured, a
value is never overwritten by a later `NULL`.** Unlike the `terminus_*`
columns (which use `CASE WHEN ... THEN NULL` to wipe), disruption
columns are sticky:

```sql
disruption_category    = COALESCE(excluded.disruption_category, disruption_category),
disruption_cause_code  = COALESCE(excluded.disruption_cause_code, disruption_cause_code),
disruption_window_from = COALESCE(excluded.disruption_window_from, disruption_window_from),
disruption_window_to   = COALESCE(excluded.disruption_window_to, disruption_window_to),
```

Rationale: the trip-level `<m t="h">` HIM element (category + window) is
dropped from `/fchg` once its `to` time passes, so a refetch after the
window would otherwise null-overwrite a previously captured reason. With
`COALESCE` the reason persists - and remains valid (and more relevant)
when a train flips to cancelled. Tradeoff (accepted): a value can only be
*replaced* by a non-`NULL`, never retracted to `NULL`. Reasons are
refined, not withdrawn, so this is correct; cause-code refinement
(`NULL`->`34`, `34`->`44`) still applies since those are non-`NULL`.

**Legacy `reason` column - keep writing NULL, drop from export only.**
The physical `reason` column stays in the schema and the INSERT/ON
CONFLICT keep referencing it (`storage.py:106` passes `r.reason`,
`:115-117` lists it, `:123` does `reason = excluded.reason`); since
`ArrivalRecord.reason` is now always `None`, every write stores `NULL`.
This avoids touching the upsert SQL or the dataclass write path. The
**exporter** stops selecting and emitting `reason` (the two `SELECT`s at
`exporter.py:40` and `:195`, plus the output dict). It was always
`NULL`, so dropping the export is safe and no consumer depended on it.
(SQLite cannot cheaply drop a column; leaving it inert is the lowest-risk
choice.)

### 3. cause_codes.py - decode table (new module)

```python
CAUSE_CODES: dict[int, str] = {
    34: "Verspätung eines vorausfahrenden Zuges",
    # 43, 44, 48, ... seeded from DB Verspätungsursachen list
}

def decode_cause(code: int | None) -> str | None:
    return CAUSE_CODES.get(code) if code is not None else None
```

- Seeded from DB's published Verspätungsursachen (delay-cause) list plus
  the codes observed in production (34, 43, 44, 48).
- Unknown code -> `cause_text = None`; the raw `cause_code` is still
  emitted, so no information is lost and the table can be extended later
  to re-decode history.
- Lives in code (not the DB) so a table update re-decodes all historical
  rows at export time.
- **Exact German strings for each code are TBD during implementation** -
  resolve against the DB Verspätungsursachen reference; where a code's
  meaning cannot be confirmed, omit it (number-fallback) rather than
  guess.

### 4. exporter.py - assemble nested object

Both query sites (`_query_window`, the archive query) currently `SELECT
... reason ...` and `dict(zip(cols, row))`. Change to select the four
new columns and assemble:

```json
"disruption": {
  "category":   "Störung",
  "cause_code": 34,
  "cause_text": "Verspätung eines vorausfahrenden Zuges",
  "window": { "from": "2026-06-10T04:19:00Z", "to": "2026-06-10T06:30:00Z" }
}
```

- `disruption` is `null` when no `disruption_category` and no
  `disruption_cause_code` are present.
- `cause_text` = `decode_cause(cause_code)` (may be `null`).
- `window` is `null` when both bounds are absent; individual bounds may
  be `null`.
- Remove `reason` from the exported arrival dict.

### 5. Web UI - reduced render

Read `disruption` from each arrival. Render style: **badge + tap to
expand**.

- **Collapsed (default):** `⚠ {category}` as a small badge next to the
  train row. One word, no overflow on mobile.
- **Expanded (after tap/click):** reveal `cause_text` (when non-null)
  and the window formatted `HH:MM-HH:MM` (Europe/Berlin).
- No disruption -> no badge.
- Reduction logic lives in the UI/TS layer (render + `stats.ts`); the
  JSON is untouched.

**Security:** `disruption.category`, `cause_text`, and the window are
bot-written values flowing into the DOM. They MUST be escaped/coerced
before `innerHTML`, consistent with the prior stored-XSS fix
(`b8e8eff`, H1). Prefer `textContent`; if `innerHTML` is unavoidable,
route through the existing escape helper.

## Error handling

| Situation                        | Behaviour                                  |
|----------------------------------|--------------------------------------------|
| No `<m>` elements                | `disruption = null`; on-time path unchanged |
| `t="h"` present, no `t="d"` code | category + window only; `cause_code = null` |
| `t="d"` code present, no `t="h"` | `cause_code` (+ decoded text) only; `category = null` |
| Unknown cause code               | `cause_text = null`; raw `cause_code` kept  |
| Malformed `from`/`to`            | affected bound -> `null`; category still emitted |

## Testing

**Parser (`test_parser.py`):**
- cancelled trip with trip-level `t="h"` HIM -> category + window parsed.
- delayed trip with stop-level `t="d" c="34"` -> cause_code 34.
- `t="f" c="0"` present -> ignored, not treated as a cause.
- codes on **both** `ar` and `dp` -> `ar` wins (fixed scan order).
- on-time trip, no `<m>` -> `disruption is None`.
- `from`/`to` converted Europe/Berlin -> UTC correctly.

**Exporter (`test_exporter.py`):**
- nested `disruption` object assembled from columns.
- `null` when no category and no code.
- decode hit (known code -> text) and miss (unknown -> `cause_text` null,
  code preserved).
- `reason` key absent from output.

**Decode (`test_cause_codes.py`):**
- known code -> expected string; unknown -> `None`; `None` -> `None`.

**UI:**
- badge renders for a disrupted arrival, absent for on-time.
- tap toggles expanded detail.
- XSS payload injected into `category`/`cause_text` is escaped, not
  executed.

## Migration / rollout

- New columns added by idempotent `ALTER TABLE` on next VM start; existing
  rows get `NULL` disruption (historical reasons are unrecoverable - the
  `/fchg` window has rolled past).
- `latest.json` consumers: `reason` key disappears, `disruption` key
  appears. Since `reason` was always `null`, no consumer depended on it.
- Semver: `feat` (new user-visible data + UI) -> MINOR bump per release
  procedure.

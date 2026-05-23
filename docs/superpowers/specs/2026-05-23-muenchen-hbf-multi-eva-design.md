# München Hbf as canonical Munich-direction terminus (multi-EVA poll)

**Status:** Design
**Date:** 2026-05-23
**Scope:** `fetcher/src/s7bb_fetcher/terminus.py`, `parser.py`, `storage.py` migration
**Related:** [terminus-tracking-design](2026-05-22-terminus-tracking-design.md), [terminus-delay-fix](2026-05-23-terminus-delay-fix-design.md), [terminus-health-export](2026-05-23-terminus-health-export.md)

## Problem

On 2026-05-23, DB began routing S7-Süd through the Munich Stammstrecke
tief platforms and continuing east to Höhenkirchen-Siegertsbrunn /
Kreuzstraße / Aying. The exporter still classifies these as
`direction_bucket = "muenchen"` (parser fix from v0.8.2 carries the
`"München" in path` rule). But terminus tracking polls EVA `8098261`
("München Hbf Gl.27-36", the surface S-Bahn platforms), which these
through-running trains never call at.

Observed production state at 2026-05-23T19:00Z:

- `terminus_health` for EVA `8098261`: `zero_match_streak = 19`
  (~95 minutes of consecutive zero-match cycles).
- 339 of 346 muenchen rows in the 7-day window have
  `terminus_status = null`.
- 2 rows misclassified `cancelled` via cutoff drilldown
  (terminus `Höhenkirchen-Siegertsbrunn`, `Kreuzstraße`).
- `aggregates.today.muenchen` and `aggregates.last_7_days.muenchen`
  both null.

## Goal

From the perspective of a Baierbrunn resident asking "can I reach the
city today?", reaching **München Hbf in any form** is success.
Anything past Hbf is irrelevant to that question. The fetcher must
detect Hbf arrivals regardless of whether DB routes through
`Hbf Gl.27-36` (surface) or `Hbf (tief)` (underground Stammstrecke).

## Non-goals

- Tiered reachability metrics (e.g. "reached Heimeranplatz counts as
  partial success"). Out of scope; keep the current binary
  arrived/short_turn/cancelled triad.
- Backfilling false-positive `cancelled` rows already written today.
  Accepting a lossy day. The next normal cycle resumes correct
  classification once the fix deploys.
- New aggregates or UI changes. Data-only fix.

## Design

### Multi-EVA terminus poll for the muenchen bucket

`TERMINUS_EVA_FOR_BUCKET["muenchen"]` becomes a tuple of EVAs covering
both Hbf variants:

```python
MUENCHEN_HBF_EVA      = "8098261"   # Gl.27-36, surface S-Bahn
MUENCHEN_HBF_TIEF_EVA = "????????"  # resolved in plan stage
MUENCHEN_HBF_EVAS     = (MUENCHEN_HBF_EVA, MUENCHEN_HBF_TIEF_EVA)

TERMINUS_EVA_FOR_BUCKET = {
    "muenchen":       MUENCHEN_HBF_EVAS,    # tuple
    "wolfratshausen": (WOLFRATSHAUSEN_EVA,) # tuple of one for symmetry
}
```

`update_terminus_for_window` iterates the tuple per bucket:

1. Fetch `/fchg` for each EVA in the tuple. Build a merged trip-prefix
   index by updating dict-style across feeds. A single S-Bahn run is
   physically routed through exactly one of the two Hbf entities, so
   collisions are not expected; if they occur, last-write wins is
   acceptable (both entries would describe the same trip).
2. Fetch `/plan` for each EVA at the relevant hour keys.
3. `classify(pending, merged_entry, ...)` unchanged — operates on the
   merged result.
4. `terminus_health` is recorded **per EVA** (already the case). One
   side going dark for 3+ cycles still triggers a warning.

A bucket-level failure (both EVAs error) leaves the group pending —
same behavior as today's single-EVA error path.

### Drilldown cap at Munich Hbf

`drilldown_short_turn` currently walks `dp_ppth` reverse from
`parts[-1]` (true terminus) toward Baierbrunn. When the path is
`...|Pullach|...|München Hbf (tief)|...|Aying`, the walk visits
eastern Munich stations (Ostbahnhof, Berg am Laim, …) — none of which
are in `STATION_NAME_TO_EVA`, so each logs a noisy warning and gets
skipped.

Change: before walking, scan `parts` left-to-right for the first
station name matching any Munich Hbf variant (`"München Hbf Gl.27-36"`
or `"München Hbf (tief)"`). A path containing both would be physically
impossible for one S-Bahn run; the first match suffices either way.
If found, truncate `parts` to `parts[:hbf_idx+1]`.
The walk now starts at Hbf and proceeds toward Baierbrunn. Stations
east of Hbf are never touched.

If no Hbf variant appears in the path, fall back to current behavior
(walk from true terminus). This preserves the wolfratshausen direction
unchanged.

### Station map extension

`STATION_NAME_TO_EVA` gains the tief station name → tief EVA mapping.
Name resolution (the exact label DB emits in `dp_ppth`) is a plan-stage
task: run `/station/München Hbf` via the API or sample a current
through-running `dp_ppth` from the live SQLite DB on the VM.

### Travel time and cutoff

Unchanged. `TRAVEL_TIME_MINUTES["muenchen"] = 35` is the
Baierbrunn → Hbf-surface schedule. Hbf-tief arrival is within 1–2 min
of Hbf-surface; not worth a per-variant constant.
`CUTOFF_GRACE_MINUTES = 60` unchanged.

### Health table

`terminus_health` schema unchanged — already keyed by EVA. The fix
adds a second row for the tief EVA the first time a muenchen cycle
polls it. The 3-streak warning will catch any future EVA drift on
either platform variant.

## Migration / rollout

- Code change ships in a single PR. SemVer: `fix` (no API or schema
  change → PATCH bump, 0.8.3).
- VM redeploy: `docker compose build && docker compose up -d
  s7bb-fetcher` (per memory note on cached image gotcha).
- No SQL migration: `arrivals` schema unchanged. `terminus_health`
  picks up the new EVA row on first write.
- No UI change required.

## Risks

1. **Wrong tief EVA.** If the EVA we add doesn't match what DB
   actually uses, we'll just keep seeing the same zero-match warning,
   but on a different EVA. Caught quickly by `terminus_health`.
   Mitigation: resolve via `/station` API in plan stage before
   shipping, verify by inspecting a current through-running
   `dp_ppth` in the production DB.
2. **DB switches back to surface routing.** Multi-EVA poll handles
   this transparently — surface EVA starts matching again, tief goes
   quiet. No code change required.
3. **Third Hbf variant.** If DB invents another EVA, we re-add to the
   tuple. Loose coupling cost: one constant edit per future variant.
4. **API quota.** One extra `/fchg` per 5-min cycle plus extra
   `/plan` calls for the second EVA's hour keys. Quota headroom is
   ample today (per existing logs); not a blocker.

## Testing

- Unit: `test_terminus.py` extends with a multi-EVA fixture (two
  feed XMLs, asserts merged index hits regardless of which feed
  carried the trip).
- Unit: drilldown test with a path containing `"München Hbf (tief)"`
  in the middle, asserts walk stops at Hbf and never visits
  hypothetical eastern stations.
- Integration / VM: after deploy, watch `terminus_health` for both
  Munich EVAs to settle at `zero_match_streak = 0` within 3 cycles.
  Spot-check a current Aying-terminus trip → expect
  `terminus_status = arrived` once it physically passes Hbf.

## Out of scope (parking lot)

- Renaming the bucket. `direction_bucket = "muenchen"` is fine.
- Per-train terminus EVA derivation from `dp_ppth`. More efficient but
  more fragile; revisit only if multi-EVA poll runs into quota issues.
- Reachability tiers. Worth considering if Baierbrunn residents ever
  give feedback that "made it to Heimeranplatz" should count as
  partial success — for now, binary arrived/not is enough.

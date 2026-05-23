# München Hbf as canonical Munich-direction terminus (multi-EVA poll)

**Status:** Design
**Date:** 2026-05-23
**Scope:** `fetcher/src/s7bb_fetcher/terminus.py` (multi-EVA polling, drilldown cap, health re-keying), `storage.py` (`terminus_health` CREATE statement re-keyed by bucket), `exporter.py` (rename `eva` field → `bucket` in health export), one-shot SQL migration (drop & recreate `terminus_health`).
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
- Backfilling false-positive `cancelled` / `null` rows already written
  for 2026-05-23. Accepting a lossy day. The next normal cycle resumes
  correct classification once the fix deploys. CHANGELOG entry for the
  release must call out the affected date so future audits do not
  re-investigate. (Cross-ref: same convention applied for
  `[[project_classify_passthrough]]` on the parser-side fix earlier
  the same day.)
- New aggregates or UI changes. Data-only fix.

## Design

### Multi-EVA terminus poll for the muenchen bucket

`TERMINUS_EVA_FOR_BUCKET["muenchen"]` becomes a tuple of EVAs covering
both Hbf variants:

```python
MUENCHEN_HBF_EVA      = "8098261"   # Gl.27-36, surface S-Bahn
MUENCHEN_HBF_TIEF_EVA = "8098263"   # Hbf (tief), Stammstrecke S-Bahn
MUENCHEN_HBF_EVAS     = (MUENCHEN_HBF_EVA, MUENCHEN_HBF_TIEF_EVA)

TERMINUS_EVA_FOR_BUCKET = {
    "muenchen":       MUENCHEN_HBF_EVAS,    # tuple
    "wolfratshausen": (WOLFRATSHAUSEN_EVA,) # tuple of one for symmetry
}
```

Tief EVA resolved 2026-05-23 via
`GET /station/München%20Hbf%20%28tief%29` → returned
`eva="8098263" name="München Hbf (tief)" ds100="MHT"`. Sibling EVA
`8098262` is "München Hbf Gl.5-10" (additional surface platforms,
not on the S7 routing), explicitly excluded.

`update_terminus_for_window` iterates the tuple per bucket:

1. Fetch `/fchg` for each EVA in the tuple. Build a merged trip-prefix
   index by `dict.update` across feeds. A single S-Bahn run is
   physically routed through exactly one of the two Hbf entities
   (`dp_ppth` is single-direction from Baierbrunn and one inbound run
   cannot call at both surface and tief platforms), so collisions are
   not expected; if they occur, last-write wins is acceptable (both
   entries would describe the same trip and carry the same `ar/@ct`).
2. Fetch `/plan` for each EVA at the relevant hour keys. The
   `plan_pt` dict is similarly merged by `dict.update` across both
   (EVA, hour) iterations — same idempotency rationale: a given
   trip-prefix appears in at most one EVA's plan per cycle, and if
   somehow in both, the planned `ar/@pt` would be the same Berlin-local
   minute either way.
3. `classify(pending, merged_entry, ...)` unchanged — operates on the
   merged result.
4. `terminus_health` keying changes — see next subsection.

A bucket-level failure (all EVAs in the tuple error) leaves the group
pending — same behavior as today's single-EVA error path.

#### Considered alternative: scalar + extras map

An alternative is to keep `TERMINUS_EVA_FOR_BUCKET` scalar and add a
sibling `TERMINUS_EVA_EXTRAS = {"muenchen": (MUENCHEN_HBF_TIEF_EVA,)}`.
Smaller diff (wolfratshausen call sites untouched) but introduces two
sources of truth that must stay aligned. Rejected: uniform tuple is
worth the one-line wolfratshausen change because future per-direction
multi-EVA additions (e.g. a third Hbf variant, or split-routing on
the Wolfratshausen line) become a constant edit instead of touching
two structures.

### Drilldown cap at Munich Hbf

`drilldown_short_turn` currently walks `reversed(parts[:-1])`
(one-before-terminus toward Baierbrunn). When the path is
`...|Pullach|...|München Hbf (tief)|...|Aying`, that walk starts at
the station immediately before Aying and visits eastern Munich
stations (Ostbahnhof, Berg am Laim, …) — none of which are in
`STATION_NAME_TO_EVA`, so each logs a noisy warning and gets skipped.

Change: before walking, scan `parts` left-to-right for the first
station name matching any Munich Hbf variant (`"München Hbf Gl.27-36"`
or `"München Hbf (tief)"`). A single inbound S-Bahn run cannot
physically call at both Hbf entities — surface (Gl.27-36) and tief
are mutually exclusive routings — so a `dp_ppth` containing both is
impossible by construction, and the first match suffices either way.
If found, truncate `parts` to `parts[:hbf_idx+1]`.
The walk then proceeds as `reversed(parts[:-1])` over the truncated
list, i.e. from the station immediately before Hbf toward Baierbrunn.
Hbf itself and stations east of Hbf are never visited.

If no Hbf variant appears in the path, fall back to current behavior
(walk from one-before true terminus). This preserves the wolfratshausen
direction unchanged.

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

### Health table — re-keyed by bucket, not EVA

Per-EVA keying is incompatible with multi-EVA polling. If muenchen
trips route through only one Hbf variant (the steady state once DB
picks an assignment), the *other* variant sees `pending_count=N,
match_count=0` every cycle and trips the 3-cycle warning permanently
even though tracking is healthy — the trains simply aren't there.

Resolution: `terminus_health` becomes keyed by **bucket** (`muenchen`
/ `wolfratshausen`), not EVA. The orchestrator records one health
row per bucket per cycle, using the merged match tally across all
EVAs in the tuple:

```python
match_count_bucket = sum of (entries matched per EVA) across the tuple
pending_count_bucket = len(group)  # unchanged
# warn iff match_count_bucket == 0 across the bucket
```

Semantics: the warning fires when the bucket as a whole loses track
of its pending trains — which is the user-facing concern ("can I
reach this terminus at all?"). A single-EVA outage (DB returns 5xx
for one EVA but the other still matches) does not trip the warning,
correctly: tracking is degraded but not broken.

#### Schema migration

`terminus_health` is currently `PRIMARY KEY(eva)`. Re-keying requires:

1. New column `bucket TEXT NOT NULL`; drop `eva` (no longer
   meaningful at row level — a bucket can span multiple EVAs).
2. New `PRIMARY KEY(bucket)`.
3. One-shot SQLite migration: `DROP TABLE terminus_health;
   CREATE TABLE terminus_health(bucket TEXT PRIMARY KEY,
   zero_match_streak INTEGER NOT NULL DEFAULT 0,
   updated_at TEXT NOT NULL);`. Health is a derived metric,
   regenerated within 1-2 cycles after deploy. No backfill needed.
4. Exporter (`exporter.py`) currently emits `eva` in
   `terminus_health` JSON entries (per
   `[[project_terminus_health_export]]`). Field renames to `bucket`.
   Site has no consumer yet — safe to rename without UI change.

This migration moves spec scope back to include `storage.py` (CREATE
statement) and `exporter.py` (field rename). Updating Scope header
accordingly.

#### Considered alternative: per-EVA attribution via dp_ppth

Could keep per-EVA keying by counting `pending_count` per EVA based
on which Hbf variant appears in each pending train's `dp_ppth`.
Rejected: more code, more brittleness (depends on `dp_ppth` being
populated and parseable for every pending row — not guaranteed for
legacy rows), and the bucket-level metric is what the warning
actually means to a human reader.

## Migration / rollout

- Code change ships in a single PR. SemVer: `fix` (no public API
  change; internal `terminus_health` schema change is exporter-only
  and the site has no consumer yet → PATCH bump, 0.8.3). If the
  site had a live `terminus_health` consumer the field rename
  (`eva` → `bucket`) would be a breaking export change and force a
  MINOR bump; re-evaluate at release time by grepping `site/` for
  `terminus_health` references.
- VM redeploy: `docker compose build && docker compose up -d
  s7bb-fetcher` (per `[[feedback_docker_rebuild]]` — `up -d` alone
  reuses cached image).
- SQL migration: one-shot `DROP TABLE IF EXISTS terminus_health;
  CREATE TABLE terminus_health(...) ` keyed by bucket. Health is a
  derived 3-cycle streak, so dropping is harmless — reaccrues within
  ~15 minutes. `arrivals` schema unchanged.
- CHANGELOG: under `### Fixed` for 0.8.3, note (a) multi-EVA poll
  for München Hbf surface + tief, (b) `terminus_health` re-keyed by
  bucket (consumers must read `bucket` not `eva`), (c) 2026-05-23
  rows for muenchen bucket are not backfilled (see Non-goals).

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
4. **API quota.** Added load per 5-min cycle for the muenchen bucket:
   +1 `/fchg` (the tief EVA) and +N `/plan` calls where N is the
   number of distinct (date, hour) keys in the pending group —
   typically 1 (peak: 2 when a cycle straddles the hour boundary
   for trains spread across `_hour_keys`). At 5-min cadence:
   12 cycles/h × 24 h = **288 extra `/fchg` per day** and
   **288–576 extra `/plan` per day**. Wolfratshausen bucket
   unaffected. Confirm against current DB Timetables marketplace
   quota at deploy time (free tier headroom historically
   comfortable per existing run logs, but include a one-line
   sanity-check in the PR description).

## Testing

- Unit: `test_terminus.py` extends with a multi-EVA fixture (two
  `/fchg` XMLs, one carrying the trip and one empty; asserts
  `classify` succeeds regardless of which feed carried the trip).
- Unit: drilldown test with `dp_ppth` containing
  `"München Hbf (tief)"` mid-path and `"Aying"` as terminus.
  Assert (a) walk truncates at Hbf, (b) walk never calls
  `fetch_full_changes` for any eastern station, (c) no
  `"unknown intermediate"` warnings emitted.
- Unit: health-table test that confirms bucket-level streak: feed
  one EVA matches all trips, other EVA matches none → assert
  `terminus_health` row for `bucket='muenchen'` has
  `zero_match_streak = 0` (no false warning). Then both EVAs
  empty → assert streak increments.
- Unit: storage test for new `terminus_health` CREATE — bucket as
  PRIMARY KEY, UPSERT on bucket conflict.
- Unit: exporter test confirms `terminus_health[].bucket` (not
  `eva`) in JSON output.
- Integration / VM: after deploy, watch `terminus_health` for the
  `muenchen` bucket row to settle at `zero_match_streak = 0`
  within 3 cycles (~15 min). The bucket-keyed row replaces the two
  per-EVA rows; expect to see one `muenchen` and one
  `wolfratshausen` row after the first cycle, not the prior pair
  `(8098261, 8006550)`.
- Integration / VM: spot-check a current Aying-terminus trip via
  `sqlite3 data/s7bb.db "SELECT terminus_status, terminus_delay_minutes
  FROM arrivals WHERE direction_bucket='muenchen' AND
  scheduled_time > datetime('now','-1 hour')"` → expect
  `terminus_status = arrived` once it physically passes Hbf, with a
  finite delay (not null).

## Out of scope (parking lot)

- Renaming the bucket. `direction_bucket = "muenchen"` is fine.
- Per-train terminus EVA derivation from `dp_ppth`. More efficient but
  more fragile; revisit only if multi-EVA poll runs into quota issues.
- Reachability tiers. Worth considering if Baierbrunn residents ever
  give feedback that "made it to Heimeranplatz" should count as
  partial success — for now, binary arrived/not is enough.

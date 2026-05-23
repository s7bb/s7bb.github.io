# Terminus Delay Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `terminus_delay_minutes` reflect real lateness by sourcing the planned terminus arrival time from `/plan/{terminus_eva}/{date}/{hour}` when `/fchg` omits `pt`. Resolves [#51](https://github.com/s7bb/s7bb.github.io/issues/51).

**Architecture:** Inside `update_terminus_for_window`, fetch the terminus `/plan` for the hours covered by pending trains, index by trip-id prefix, and feed the planned `pt` into `classify()` as a third tier after `/fchg` pt. No schema change, no parser change, no exporter change — only `fetcher/src/s7bb_fetcher/terminus.py` and its tests.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `ruff`, `lxml`, SQLite. Site untouched.

**Spec:** `docs/superpowers/specs/2026-05-23-terminus-delay-fix-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `fetcher/src/s7bb_fetcher/terminus.py` | modify | Add `_build_plan_pt_index`, `_hour_keys` helpers; extend `_arrival_delay_minutes` + `classify`; wire `/plan` fetch in `update_terminus_for_window` |
| `fetcher/tests/test_terminus.py` | modify | TDD coverage for the helpers, the new classify path, the orchestrator wiring, and the plan-HTTP-failure tolerance |
| `fetcher/tests/fixtures/terminus_munich_delayed_no_pt.xml` | create | `/fchg`-style fixture: only `ct`, no `pt` (matches live S-Bahn) |
| `fetcher/tests/fixtures/terminus_munich_plan.xml` | create | `/plan`-style fixture: `<ar pt="...">` populated for `TRIP_PREFIX` |
| `CHANGELOG.md` | modify | `[Unreleased]` entry (becomes `[0.7.2]` at release) |
| `fetcher/pyproject.toml` + `fetcher/uv.lock` | modify (release task) | Version bump to `0.7.2` |

---

### Task 1: Add `/fchg` fixture without `pt`

**Files:**
- Create: `fetcher/tests/fixtures/terminus_munich_delayed_no_pt.xml`

- [ ] **Step 1: Compare against the existing delayed fixture so the new file differs by exactly the `pt` removal**

Run: `cat fetcher/tests/fixtures/terminus_munich_delayed.xml`
Expected: single `<s id="42-2605051200-22">` with `<ar pt="..." ct="...">`.

- [ ] **Step 2: Create the new fixture without the `pt` attribute**

Write `fetcher/tests/fixtures/terminus_munich_delayed_no_pt.xml`. Keep `ct` exactly 5 minutes after the original `pt` so the existing 5-min assertion stays meaningful once the plan path supplies the planned time.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="München Hbf Gl.27-36">
  <s id="42-2605051200-22">
    <ar ct="2605051345"/>
  </s>
</timetable>
```

- [ ] **Step 3: Commit**

```bash
git add fetcher/tests/fixtures/terminus_munich_delayed_no_pt.xml
git commit -m "test(terminus): add /fchg fixture without pt to mirror live S-Bahn"
```

---

### Task 2: Add `/plan` fixture for the matching hour

**Files:**
- Create: `fetcher/tests/fixtures/terminus_munich_plan.xml`

- [ ] **Step 1: Write the fixture**

The `/plan` endpoint returns `<s>` blocks with both `<ar>` and `<dp>` carrying `pt`. We need `<ar pt="2605051340">` so that `ct=2605051345` (from Task 1) yields a 5-minute delta.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="München Hbf Gl.27-36">
  <s id="42-2605051200-22">
    <tl f="S" t="p" o="800725" c="S" n="6042"/>
    <ar pt="2605051340" pp="3" l="S7" ppth="Donnersbergerbrücke|Hbf"/>
    <dp pt="2605051341" pp="3" l="S7" ppth="Karlsplatz|Marienplatz"/>
  </s>
</timetable>
```

- [ ] **Step 2: Commit**

```bash
git add fetcher/tests/fixtures/terminus_munich_plan.xml
git commit -m "test(terminus): add /plan fixture for delay-source lookup"
```

---

### Task 3: Unit test — `_build_plan_pt_index`

**Files:**
- Modify: `fetcher/tests/test_terminus.py`

- [ ] **Step 1: Write the failing test**

Add at the end of the file (after the existing pure-helper tests, before the orchestrator tests).

```python
def test_build_plan_pt_index_keys_by_trip_prefix_and_uses_ar_pt():
    from s7bb_fetcher.terminus import _build_plan_pt_index
    idx = _build_plan_pt_index(_load("terminus_munich_plan.xml"))
    assert idx == {TRIP_PREFIX: "2605051340"}


def test_build_plan_pt_index_skips_blocks_without_ar_or_id():
    from s7bb_fetcher.terminus import _build_plan_pt_index
    xml = etree.fromstring(
        b'<timetable>'
        b'  <s id=""><ar pt="2605051340"/></s>'           # bad id
        b'  <s id="single"><ar pt="2605051340"/></s>'     # no separator
        b'  <s id="42-2605051200-22"></s>'                # no ar
        b'  <s id="42-2605051200-22"><ar/></s>'           # ar without pt
        b'</timetable>',
        parser=_PARSER,
    )
    assert _build_plan_pt_index(xml) == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd fetcher && uv run pytest tests/test_terminus.py::test_build_plan_pt_index_keys_by_trip_prefix_and_uses_ar_pt -v`
Expected: `ImportError` (no `_build_plan_pt_index` symbol yet) or `AttributeError`.

- [ ] **Step 3: Add the helper to `terminus.py`**

Insert just below `build_index()` (around line 111) in `fetcher/src/s7bb_fetcher/terminus.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k "build_plan_pt_index" -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/terminus.py fetcher/tests/test_terminus.py
git commit -m "feat(terminus): add _build_plan_pt_index helper"
```

---

### Task 4: Unit test — `_hour_keys`

**Files:**
- Modify: `fetcher/tests/test_terminus.py`

- [ ] **Step 1: Write the failing test**

```python
def test_hour_keys_dedups_and_uses_terminus_local_hour():
    """Two pending trains 10 min apart at Baierbrunn, same target hour at
    München (10:30 UTC + 35 min ≈ 13:05 Berlin; 10:40 UTC + 35 min ≈
    13:15 Berlin) → both fall into the same (date, "13") plan hour."""
    from s7bb_fetcher.terminus import _hour_keys
    group = [
        _pending(scheduled_iso="2026-05-05T10:30:00+00:00"),
        _pending(scheduled_iso="2026-05-05T10:40:00+00:00"),
    ]
    assert _hour_keys(group, bucket="muenchen") == {("260505", "13")}


def test_hour_keys_spans_two_hours_when_pending_straddles_boundary():
    from s7bb_fetcher.terminus import _hour_keys
    # 11:20 UTC + 35 min = 12:55 Berlin → hour "13" (Berlin) — actually 13:55, so "13"
    # 11:35 UTC + 35 min = 13:10 Berlin → hour "14" (Berlin) — actually 14:10, so "14"
    # Pick clearer inputs:
    # 11:00 UTC + 35 min = 13:35 Berlin (CEST) → "13"
    # 11:30 UTC + 35 min = 14:05 Berlin (CEST) → "14"
    group = [
        _pending(scheduled_iso="2026-05-05T11:00:00+00:00"),
        _pending(scheduled_iso="2026-05-05T11:30:00+00:00"),
    ]
    assert _hour_keys(group, bucket="muenchen") == {("260505", "13"), ("260505", "14")}


def test_hour_keys_uses_wolfratshausen_offset():
    from s7bb_fetcher.terminus import _hour_keys
    # 11:00 UTC + 20 min = 13:20 Berlin → "13"
    group = [_pending(scheduled_iso="2026-05-05T11:00:00+00:00", bucket="wolfratshausen")]
    assert _hour_keys(group, bucket="wolfratshausen") == {("260505", "13")}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k hour_keys -v`
Expected: ImportError / AttributeError.

- [ ] **Step 3: Add the helper**

Insert in `fetcher/src/s7bb_fetcher/terminus.py` between `_cutoff` (line 133) and `_arrival_delay_minutes`:

```python
def _hour_keys(group: list[PendingTrain], bucket: str) -> set[tuple[str, str]]:
    """Distinct (YYMMDD, HH) Europe/Berlin plan-hour keys covering the
    expected terminus arrival times of every train in `group`.

    Returns the deduplicated set used to issue ``/plan/{eva}/{date}/{hour}``
    calls. Times convert to Europe/Berlin because the API's date/hour
    path components are local.
    """
    offset = timedelta(minutes=TRAVEL_TIME_MINUTES.get(bucket, 35))
    out: set[tuple[str, str]] = set()
    for p in group:
        sched = datetime.fromisoformat(p.scheduled_time)
        local = (sched + offset).astimezone(_DE_TZ)
        out.add((local.strftime("%y%m%d"), local.strftime("%H")))
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k hour_keys -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/terminus.py fetcher/tests/test_terminus.py
git commit -m "feat(terminus): add _hour_keys helper for plan-hour set"
```

---

### Task 5: Extend `_arrival_delay_minutes` with the planned_pt fallback

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py:136-153`
- Modify: `fetcher/tests/test_terminus.py`

- [ ] **Step 1: Write the failing tests**

Add to `fetcher/tests/test_terminus.py`:

```python
def test_arrival_delay_uses_fchg_pt_when_present():
    """If /fchg carries pt (long-distance services do), it wins over the plan fallback."""
    from s7bb_fetcher.terminus import _arrival_delay_minutes, build_index
    entry = build_index(_load("terminus_munich_delayed.xml"))[TRIP_PREFIX]
    # planned_pt argument is ignored when entry has pt
    assert _arrival_delay_minutes(entry, planned_pt="2605059999") == 5


def test_arrival_delay_falls_back_to_planned_pt_when_fchg_lacks_it():
    from s7bb_fetcher.terminus import _arrival_delay_minutes, build_index
    entry = build_index(_load("terminus_munich_delayed_no_pt.xml"))[TRIP_PREFIX]
    assert _arrival_delay_minutes(entry, planned_pt="2605051340") == 5


def test_arrival_delay_returns_zero_when_no_pt_anywhere():
    from s7bb_fetcher.terminus import _arrival_delay_minutes, build_index
    entry = build_index(_load("terminus_munich_delayed_no_pt.xml"))[TRIP_PREFIX]
    assert _arrival_delay_minutes(entry, planned_pt=None) == 0


def test_arrival_delay_returns_zero_when_ct_missing():
    from s7bb_fetcher.terminus import _arrival_delay_minutes
    xml = etree.fromstring(
        b'<timetable><s id="42-2605051200-22"><ar/></s></timetable>',
        parser=_PARSER,
    )
    entry = xml.find(".//s")
    assert _arrival_delay_minutes(entry, planned_pt="2605051340") == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k arrival_delay -v`
Expected: 4 fail with `TypeError: _arrival_delay_minutes() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Rewrite the function**

Replace `_arrival_delay_minutes` in `fetcher/src/s7bb_fetcher/terminus.py` (lines 136-153) with:

```python
def _arrival_delay_minutes(
    entry: etree._Element, planned_pt: str | None = None
) -> int:
    """Compute ct - pt in whole minutes; 0 if either side missing.

    /fchg carries ``pt`` for long-distance services but omits it for
    S-Bahn. ``planned_pt`` is the raw DB time string (``YYMMDDHHMM``)
    looked up from a parallel ``/plan`` call when /fchg has no ``pt``.
    """
    ar = entry.find("ar")
    if ar is None:
        return 0
    ct = ar.get("ct")
    if not ct:
        return 0
    pt = ar.get("pt") or planned_pt
    if not pt:
        return 0
    return int((_parse_db_time(ct) - _parse_db_time(pt)).total_seconds() / 60)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k arrival_delay -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full terminus test module to check the existing test still passes (it calls `_arrival_delay_minutes(entry)` with one arg via `classify`)**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`
Expected: all pre-existing tests still pass. `test_classify_arrived_on_time` is unchanged because `planned_pt` defaults to None and the fixture has no `ct`.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/terminus.py fetcher/tests/test_terminus.py
git commit -m "feat(terminus): three-tier delay source — fchg pt → plan pt → 0"
```

---

### Task 6: Plumb `planned_pt` through `classify`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py:156-213`
- Modify: `fetcher/tests/test_terminus.py`

- [ ] **Step 1: Write the failing test**

```python
def test_classify_arrived_uses_planned_pt_for_delay():
    from s7bb_fetcher.terminus import build_index, classify, trip_prefix
    idx = build_index(_load("terminus_munich_delayed_no_pt.xml"))
    pending = _pending()
    update = classify(
        pending,
        idx.get(trip_prefix(pending.train_id)),
        _BEFORE_CUTOFF,
        drilldown=lambda *_: None,
        planned_pt="2605051340",
    )
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd fetcher && uv run pytest tests/test_terminus.py::test_classify_arrived_uses_planned_pt_for_delay -v`
Expected: `TypeError: classify() got an unexpected keyword argument 'planned_pt'`.

- [ ] **Step 3: Update `classify` signature and its `_arrival_delay_minutes` call**

In `fetcher/src/s7bb_fetcher/terminus.py`, change the `classify` signature and the one call site inside it.

Signature change (line 156):

```python
def classify(
    pending: PendingTrain,
    entry: etree._Element | None,
    now: datetime,
    drilldown,
    planned_pt: str | None = None,
) -> TerminusUpdate | None:
```

Call-site change (line 191) — inside Case A "arrived" branch:

```python
        # Not cancelled at terminus → arrived (possibly late).
        return TerminusUpdate(
            pending.train_id, pending.scheduled_time,
            terminus_status="arrived",
            terminus_delay_minutes=_arrival_delay_minutes(entry, planned_pt),
            terminus_short_turn_station=None,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd fetcher && uv run pytest tests/test_terminus.py::test_classify_arrived_uses_planned_pt_for_delay -v`
Expected: PASS.

- [ ] **Step 5: Run the whole module — older `classify` callers omit `planned_pt`, must still work**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/terminus.py fetcher/tests/test_terminus.py
git commit -m "feat(terminus): thread planned_pt through classify"
```

---

### Task 7: Wire `/plan` fetch into `update_terminus_for_window`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py:291-349`
- Modify: `fetcher/tests/test_terminus.py`

- [ ] **Step 1: Write the failing orchestrator test**

Inspect the existing orchestrator tests in `test_terminus.py` (search for `update_terminus_for_window` to find the fake-client pattern already in use). Mirror it. Add:

```python
def test_update_terminus_for_window_uses_plan_pt_for_delay(tmp_path):
    """End-to-end: pending row, fake client returns /fchg without pt + /plan
    with pt → delay 5 written to DB."""
    from s7bb_fetcher.terminus import update_terminus_for_window

    db = open_db(tmp_path / "s.db")
    # Insert a pending row matching TRIP_PREFIX, scheduled 10:30 UTC München-bound.
    sched_iso = "2026-05-05T10:30:00+00:00"
    upsert_records(db, [ArrivalRecord(
        train_id=BAIERBRUNN_ID, line="S7", station="Baierbrunn",
        direction="München Hbf Gl.27-36", direction_bucket="muenchen",
        scheduled_time=sched_iso, actual_time=sched_iso, delay_minutes=0,
        cancelled=False, reason=None, train_number="6042",
        dp_ppth="Buchenhain|München Hbf Gl.27-36",
    )])

    class FakeClient:
        def __init__(self):
            self.plan_calls: list[tuple[str, str, str]] = []
            self.fchg_calls: list[str] = []
        def fetch_plan(self, eva, date, hour):
            self.plan_calls.append((eva, date, hour))
            return _load("terminus_munich_plan.xml")
        def fetch_full_changes(self, eva):
            self.fchg_calls.append(eva)
            return _load("terminus_munich_delayed_no_pt.xml")

    client = FakeClient()
    # now must be after Baierbrunn departure so the pending row is in window.
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    written = update_terminus_for_window(db, client, now=now)

    assert written == 1
    # Plan was called for the München terminus EVA at the expected Berlin hour.
    # 10:30 UTC + 35 min = 13:05 Berlin (CEST) → hour "13"
    assert client.plan_calls == [("8098261", "260505", "13")]
    assert client.fchg_calls == ["8098261"]

    row = db.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals WHERE train_id=?",
        (BAIERBRUNN_ID,),
    ).fetchone()
    assert row == ("arrived", 5)


def test_update_terminus_for_window_tolerates_plan_http_error(tmp_path):
    """If /plan raises, the cycle still completes; delay falls back to 0."""
    from s7bb_fetcher.terminus import update_terminus_for_window

    db = open_db(tmp_path / "s.db")
    sched_iso = "2026-05-05T10:30:00+00:00"
    upsert_records(db, [ArrivalRecord(
        train_id=BAIERBRUNN_ID, line="S7", station="Baierbrunn",
        direction="München Hbf Gl.27-36", direction_bucket="muenchen",
        scheduled_time=sched_iso, actual_time=sched_iso, delay_minutes=0,
        cancelled=False, reason=None, train_number="6042",
        dp_ppth="Buchenhain|München Hbf Gl.27-36",
    )])

    class FakeClient:
        def fetch_plan(self, *a, **kw):
            raise RuntimeError("boom")
        def fetch_full_changes(self, eva):
            return _load("terminus_munich_delayed_no_pt.xml")

    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    written = update_terminus_for_window(db, FakeClient(), now=now)

    assert written == 1
    row = db.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals WHERE train_id=?",
        (BAIERBRUNN_ID,),
    ).fetchone()
    # arrived; delay falls back to 0 because both /fchg.pt and plan are unavailable
    assert row == ("arrived", 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k update_terminus_for_window_uses_plan_pt -v`
Expected: failure — orchestrator never calls `fetch_plan` and writes delay 0.

- [ ] **Step 3: Modify the orchestrator**

Replace the per-bucket loop body in `update_terminus_for_window` (`fetcher/src/s7bb_fetcher/terminus.py`, around lines 320-345) with:

```python
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

        plan_pt: dict[str, str] = {}
        for date, hour in sorted(_hour_keys(group, bucket)):
            try:
                plan_xml = client.fetch_plan(eva, date, hour)
            except Exception:
                log.exception("terminus: /plan %s %s/%s failed; delays may fall back to 0",
                              eva, date, hour)
                continue
            plan_pt.update(_build_plan_pt_index(plan_xml))

        match_count = 0
        for p in group:
            entry = idx.get(trip_prefix(p.train_id))
            if entry is not None:
                match_count += 1
            update = classify(
                p, entry, now, drilldown=_drilldown,
                planned_pt=plan_pt.get(trip_prefix(p.train_id)),
            )
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
```

The `sorted(...)` keeps the `plan_calls` assertion in the test deterministic without needing a `set` order assumption.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k "update_terminus_for_window_uses_plan_pt or update_terminus_for_window_tolerates_plan_http_error" -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full terminus test module to confirm no regressions**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`
Expected: all green. If any pre-existing orchestrator test uses a `FakeClient` that does not implement `fetch_plan`, extend that fake with a no-op `fetch_plan` that returns an empty `<timetable/>` (`etree.fromstring(b"<timetable/>")`). Apply the change to the fake only — never to production code.

- [ ] **Step 6: Run the full fetcher suite + lint**

Run: `cd fetcher && uv run pytest && uv run ruff check src tests`
Expected: all green, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add fetcher/src/s7bb_fetcher/terminus.py fetcher/tests/test_terminus.py
git commit -m "fix(terminus): compute arrival delay from /plan pt when /fchg omits it (#51)"
```

---

### Task 8: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Inspect the current changelog format**

Run: `head -40 CHANGELOG.md`
Expected: a `## [Unreleased]` heading at the top (per the project's release procedure).

- [ ] **Step 2: Add the entry under `## [Unreleased]` → `### Fixed`**

Insert (creating `### Fixed` if not already present under `[Unreleased]`):

```markdown
### Fixed

- Terminus arrival delay is now computed from the planned arrival time
  returned by `/plan/{terminus_eva}/{date}/{hour}` when the `/fchg`
  feed omits `pt` (the live behaviour for every S-Bahn arrival).
  Previously `terminus_delay_minutes` was always 0 for rows in the
  `arrived` state. Historical rows are not retroactively corrected —
  re-evaluation only applies to the freshest pending window. ([#51])

[#51]: https://github.com/s7bb/s7bb.github.io/issues/51
```

If the link-reference style is not yet used in this changelog, drop the `[#51]:` reference line and inline the URL.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): note terminus delay fix (#51)"
```

---

### Task 9: Open the PR

**Files:** none beyond what's already committed.

- [ ] **Step 1: Push the branch and open the PR**

```bash
git push -u origin HEAD
gh pr create --title "fix(terminus): compute arrival delay from /plan pt when /fchg omits it" \
  --body "$(cat <<'EOF'
## Summary

- Fixes #51: every `terminus_status='arrived'` row reported
  `terminus_delay_minutes=0` because the DB Timetables `/fchg` feed
  omits the `pt` attribute for S-Bahn arrivals.
- `update_terminus_for_window` now also fetches
  `/plan/{terminus_eva}/{date}/{hour}` for the hours covering each
  cycle's pending trains, indexes the planned arrival times by
  trip-id prefix, and feeds them into `classify` as a third tier.
- No schema change, no parser change, no JSON contract change — only
  `fetcher/src/s7bb_fetcher/terminus.py` and its tests.
- Spec: `docs/superpowers/specs/2026-05-23-terminus-delay-fix-design.md`
- Plan: `docs/superpowers/plans/2026-05-23-terminus-delay-fix.md`

## Test plan

- [ ] `cd fetcher && uv run pytest -v` — full fetcher suite green
- [ ] `cd fetcher && uv run ruff check src tests` — no lint errors
- [ ] After deploy on VM, observe one `arrived` row in `latest.json`
      with `terminus_delay_minutes > 0` matching the Baierbrunn delay
      order of magnitude.
EOF
)"
```

- [ ] **Step 2: Confirm the PR URL prints; share back to the requester.**

---

### Task 10: Release v0.7.2 (post-merge)

**Files:**
- Modify: `fetcher/pyproject.toml`
- Modify: `fetcher/uv.lock`
- Modify: `CHANGELOG.md`

Per `CLAUDE.md` "Post-merge release trigger": after the PR merges into `main`, cut v0.7.2.

- [ ] **Step 1: Pull main**

```bash
git checkout main && git pull
```

- [ ] **Step 2: Bump version in `fetcher/pyproject.toml`**

Edit `version = "0.7.1"` to `version = "0.7.2"`.

- [ ] **Step 3: Sync lockfile**

```bash
cd fetcher && uv sync --no-dev && cd ..
```

- [ ] **Step 4: Rename `[Unreleased]` to `[0.7.2] - 2026-05-23` in `CHANGELOG.md`**

Use today's date (`date +%F` is the canonical source).

- [ ] **Step 5: Commit, tag, push tag**

```bash
git add fetcher/pyproject.toml fetcher/uv.lock CHANGELOG.md
git commit -m "chore(release): 0.7.2"
git tag v0.7.2
git push origin main v0.7.2
```

- [ ] **Step 6: Create the GitHub Release**

Use the dot-escaped explicit-end awk form (per the [release-awk memory] in `MEMORY.md`):

```bash
gh release create v0.7.2 --latest --title "v0.7.2" \
  --notes-file <(awk '/^## \[0\.7\.2\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md)
```

Verify the rendered body on the release page before closing the loop.

- [ ] **Step 7: Operator note for the VM**

After the release tag has built and the VM has pulled the new image (`docker compose pull && docker compose up -d s7bb-fetcher`), the operator may optionally run the one-off recovery SQL to re-evaluate the freshest window:

```bash
docker compose exec s7bb-fetcher sqlite3 /data/s7bb.db \
  "UPDATE arrivals
      SET terminus_status='pending',
          terminus_delay_minutes=NULL,
          terminus_short_turn_station=NULL
    WHERE terminus_status='arrived'
      AND terminus_delay_minutes=0
      AND scheduled_time >= datetime('now', '-2 hours');"
```

Rows older than ~2 h are not recoverable (out of the pending window). No further action required.

---

## Spec-coverage cross-check

| Spec requirement | Covered by |
|---|---|
| `_arrival_delay_minutes` accepts planned_pt; three-tier fallback | Task 5 |
| `classify(..., planned_pt=None)` pass-through | Task 6 |
| `_build_plan_pt_index(plan_xml)` helper | Task 3 |
| `_hour_keys(group, bucket)` helper | Task 4 |
| `update_terminus_for_window` fetches `/plan` per hour key, deduplicated | Task 7 |
| Partial `/plan` outage falls back to delay 0 without aborting cycle | Task 7 |
| New fixtures `terminus_munich_delayed_no_pt.xml`, `terminus_munich_plan.xml` | Tasks 1–2 |
| Adapted/new unit tests for delay path, helpers, orchestrator | Tasks 3–7 |
| CHANGELOG `[Unreleased]` entry + historical-data note | Task 8 |
| Patch release v0.7.2 + tag + GitHub Release | Task 10 |
| No schema, parser, exporter, or site change | confirmed by absence — File Structure table is the contract |

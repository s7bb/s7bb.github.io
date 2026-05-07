# SQLite Schema — `data/s7bb.db`

Single-file SQLite database written by `s7bb-fetch` and read by `s7bb-export`. Stays on the VM, never committed. WAL journal mode (`*.db-shm`, `*.db-wal` sidecar files appear at runtime).

Source of truth: [`fetcher/src/s7bb_fetcher/storage.py`](../fetcher/src/s7bb_fetcher/storage.py).

## Table: `arrivals`

One row per S7 arrival at Baierbrunn. Plan + changes XML from the DB Timetables API are merged into a single record per train.

| Column | Type | Null | Description |
|---|---|---|---|
| `id` | INTEGER | no | Primary key, autoincrement |
| `train_id` | TEXT | no | Stop ID from DB API (`<s id="...">`); stable per train run |
| `line` | TEXT | no | Always `S7` (filtered in parser) |
| `station` | TEXT | no | Always `Baierbrunn` |
| `direction` | TEXT | no | Raw terminus from `dp/@ppth`, e.g. `Wolfratshausen`, `München Hbf Gl.27-36`. Falls back to `unbekannt` |
| `direction_bucket` | TEXT | no | Normalized bucket: `wolfratshausen`, `muenchen`, or `unknown`. Default `unknown` |
| `scheduled_time` | TEXT | no | ISO 8601 UTC. DB sends `YYMMDDHHMM` Europe/Berlin local; parser converts to UTC |
| `actual_time` | TEXT | yes | ISO 8601 UTC. Equals `scheduled_time` when no change reported. `NULL` if cancelled |
| `delay_minutes` | INTEGER | yes | `actual − scheduled` in whole minutes. `0` when on time. `NULL` if cancelled. Can be negative (early arrival) |
| `cancelled` | INTEGER | no | `1` if changes XML reports `cs="c"`, else `0` |
| `reason` | TEXT | yes | DB delay/cancel message code (`m` or `msc` attribute), if present |
| `fetched_at` | TEXT | no | ISO 8601 UTC timestamp of last upsert for this row |

## Indexes

| Name | Columns | Purpose |
|---|---|---|
| `idx_dedup` | `(train_id, scheduled_time)` UNIQUE | Dedup target for `INSERT … ON CONFLICT` upsert. Re-fetches update existing row instead of inserting duplicates |
| `idx_scheduled` | `(scheduled_time)` | Range-scan for export window queries (`WHERE scheduled_time >= ?`) |

## Upsert behavior

`upsert_records()` inserts new rows; on conflict with `idx_dedup` it updates `actual_time`, `delay_minutes`, `cancelled`, `reason`, `direction_bucket`, `fetched_at`. `train_id`, `line`, `station`, `direction`, `scheduled_time` are immutable per row.

## Migrations

`_migrate()` runs on every `open_db()`. Currently handles one historical change:

- Adds `direction_bucket` column to pre-existing DBs and back-fills it from `direction` values.

Future schema changes follow the same pattern: idempotent `ALTER TABLE` guarded by a `PRAGMA table_info` check.

## How specific cases are stored

- **On time** — `actual_time = scheduled_time`, `delay_minutes = 0`, `cancelled = 0`.
- **Delayed** — `actual_time > scheduled_time`, `delay_minutes > 0`. No cap; very large delays stored as-is.
- **Early** — `actual_time < scheduled_time`, `delay_minutes < 0`. Aggregator counts as on time (`> 0` test).
- **Cancelled** — `cancelled = 1`, `actual_time = NULL`, `delay_minutes = NULL`.
- **Bunching / next train delayed past following slot** — Each train keeps its own row keyed by its own `train_id` + `scheduled_time`. No row collision; no merge. Two trains arriving close together appear as two independent rows with their true individual delays.
- **Train fully missing from plan XML** — No row inserted. Counted as `missing` by exporter when comparing observed rows to inferred 20-min slot grid.

## Querying

Open with any SQLite client:

```bash
sqlite3 data/s7bb.db
sqlite> .schema arrivals
sqlite> SELECT direction_bucket, COUNT(*) FROM arrivals GROUP BY direction_bucket;
sqlite> SELECT scheduled_time, delay_minutes, cancelled
   ...> FROM arrivals
   ...> WHERE scheduled_time >= date('now', '-1 day')
   ...> ORDER BY scheduled_time;
```

export type DirectionBucket = "muenchen" | "wolfratshausen" | "unknown";

export interface Arrival {
  train_id: string;
  line: string;
  station: string;
  direction: string;
  direction_bucket: DirectionBucket;
  scheduled_time: string;
  actual_time: string | null;
  delay_minutes: number | null;
  cancelled: boolean;
  reason: string | null;
}

export interface DayAggregate {
  total: number;
  on_time: number;
  late: number;
  cancelled: number;
  avg_delay_min: number;
}

export interface DirectionAggregate extends DayAggregate {
  missing: number;
}

export interface S7Data {
  generated_at: string;
  station: string;
  line: string;
  window_days: number;
  arrivals: Arrival[];
  aggregates: {
    today: DayAggregate & { by_direction: Record<"muenchen" | "wolfratshausen", DirectionAggregate> };
    last_7_days: DayAggregate & { by_direction: Record<"muenchen" | "wolfratshausen", DirectionAggregate> };
  };
  expected_slots: { today: Record<"muenchen" | "wolfratshausen", string[]> };
}

export async function loadData(): Promise<S7Data> {
  const url = import.meta.env.DEV
    ? "../data/latest.json"
    : `${import.meta.env.BASE_URL}data/latest.json`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to load data: ${resp.status}`);
  return resp.json() as Promise<S7Data>;
}

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function directionLabel(bucket: DirectionBucket): string {
  if (bucket === "muenchen") return "München";
  if (bucket === "wolfratshausen") return "Wolfratshausen";
  return "Unbekannt";
}

export interface SlotRow {
  slot: string;       // ISO8601 scheduled time
  record: Arrival | null;  // null = missing / no data
}

export interface UnifiedSlotRow {
  slot: string;
  muenchen: Arrival | null;
  wolfratshausen: Arrival | null;
}

/** Time-keyed union of both directions: rows align on shared scheduled time;
 *  a direction with no train at a slot gets a null cell (rendered as empty). */
export function unifiedTodayRows(data: S7Data): UnifiedSlotRow[] {
  const m = arrivalsByDirection(data, "muenchen");
  const w = arrivalsByDirection(data, "wolfratshausen");
  const byTime = new Map<string, UnifiedSlotRow>();
  const ensure = (slot: string) => {
    let r = byTime.get(slot);
    if (!r) {
      r = { slot, muenchen: null, wolfratshausen: null };
      byTime.set(slot, r);
    }
    return r;
  };
  for (const r of m) ensure(r.slot).muenchen = r.record;
  for (const r of w) ensure(r.slot).wolfratshausen = r.record;
  return [...byTime.values()].sort((a, b) => a.slot.localeCompare(b.slot));
}

function berlinDate(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Berlin",
    year: "numeric", month: "2-digit", day: "2-digit",
  }).format(d);
}

// Dev override: when VITE_DEV_NOW is set (only in dev), pretend it's that
// instant. Lets the docker-compose dev container exercise the today page
// against the latest.json checked into the repo, even when its dates are
// in the past relative to wall-clock now.
function nowForFiltering(): Date {
  const override = import.meta.env.VITE_DEV_NOW as string | undefined;
  return override ? new Date(override) : new Date();
}

// Canonical UTC ISO key. Different sources emit the same instant in
// different formats (e.g. "2026-05-09T22:19:00+00:00" vs ".000Z"); a
// canonical key lets Set/Map dedupe them. Critically, do NOT slice off
// the timezone — `new Date("...T22:19:00")` (no TZ) is parsed as the
// browser's *local* time, which would shift the displayed value by the
// browser's UTC offset.
function isoKey(iso: string): string {
  return new Date(iso).toISOString();
}

export function arrivalsByDirection(data: S7Data, bucket: "muenchen" | "wolfratshausen"): SlotRow[] {
  const now = nowForFiltering();
  const today = berlinDate(now);

  const observed = data.arrivals.filter(
    (a) =>
      a.direction_bucket === bucket &&
      berlinDate(a.scheduled_time) === today,
  );

  // Only include slots whose scheduled time is on Berlin "today" AND already past.
  // Drops stale slots from previous days and avoids "keine Daten" for future trains.
  const slots = (data.expected_slots?.today?.[bucket] ?? [])
    .filter((s) => berlinDate(s) === today && new Date(s) <= now)
    .map(isoKey);

  const allSlots = new Set([...slots, ...observed.map((a) => isoKey(a.scheduled_time))]);
  const recordByTime = new Map(observed.map((a) => [isoKey(a.scheduled_time), a]));

  return [...allSlots]
    .sort()
    .map((slot) => ({ slot, record: recordByTime.get(slot) ?? null }));
}

export function last7DaysByDay(
  data: S7Data,
  bucket?: "muenchen" | "wolfratshausen",
): { date: string; avg_delay: number; cancelled: number }[] {
  const arrivals = bucket ? data.arrivals.filter((a) => a.direction_bucket === bucket) : data.arrivals;
  const byDay = new Map<string, { delays: number[]; cancelled: number }>();
  for (const a of arrivals) {
    const date = a.scheduled_time.slice(0, 10);
    if (!byDay.has(date)) byDay.set(date, { delays: [], cancelled: 0 });
    const day = byDay.get(date)!;
    if (a.cancelled) {
      day.cancelled++;
    } else if (a.delay_minutes !== null) {
      day.delays.push(a.delay_minutes);
    }
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, { delays, cancelled }]) => ({
      date,
      avg_delay: delays.length ? delays.reduce((s, d) => s + d, 0) / delays.length : 0,
      cancelled,
    }));
}

export interface DayDirStats {
  avg_delay: number;
  cancelled: number;
  scheduled: number;
}

export interface DayDirRow {
  date: string;
  muenchen: DayDirStats;
  wolfratshausen: DayDirStats;
}

export function last7DaysByDayBothDirections(data: S7Data): DayDirRow[] {
  type Bucket = "muenchen" | "wolfratshausen";
  const acc = new Map<string, Record<Bucket, { delays: number[]; cancelled: number; scheduled: number }>>();

  for (const a of data.arrivals) {
    if (a.direction_bucket !== "muenchen" && a.direction_bucket !== "wolfratshausen") continue;
    const bucket: Bucket = a.direction_bucket;
    const date = a.scheduled_time.slice(0, 10);
    if (!acc.has(date)) {
      acc.set(date, {
        muenchen:       { delays: [], cancelled: 0, scheduled: 0 },
        wolfratshausen: { delays: [], cancelled: 0, scheduled: 0 },
      });
    }
    const day = acc.get(date)!;
    day[bucket].scheduled++;
    if (a.cancelled) {
      day[bucket].cancelled++;
    } else if (a.delay_minutes !== null) {
      day[bucket].delays.push(a.delay_minutes);
    }
  }

  const toStats = (b: { delays: number[]; cancelled: number; scheduled: number }): DayDirStats => ({
    avg_delay: b.delays.length ? b.delays.reduce((s, d) => s + d, 0) / b.delays.length : 0,
    cancelled: b.cancelled,
    scheduled: b.scheduled,
  });

  return [...acc.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, { muenchen, wolfratshausen }]) => ({
      date,
      muenchen: toStats(muenchen),
      wolfratshausen: toStats(wolfratshausen),
    }));
}

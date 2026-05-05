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

export function arrivalsByDirection(data: S7Data, bucket: "muenchen" | "wolfratshausen"): SlotRow[] {
  const today = new Date().toISOString().slice(0, 10);
  const observed = data.arrivals.filter(
    (a) => a.direction_bucket === bucket && a.scheduled_time.startsWith(today),
  );
  const observedTimes = new Set(observed.map((a) => a.scheduled_time.slice(0, 19)));

  const slots = (data.expected_slots?.today?.[bucket] ?? []).map((s) => s.slice(0, 19));
  const allSlots = new Set([...slots, ...observed.map((a) => a.scheduled_time.slice(0, 19))]);
  const recordByTime = new Map(observed.map((a) => [a.scheduled_time.slice(0, 19), a]));

  return [...allSlots]
    .sort()
    .map((slot) => ({
      slot,
      record: recordByTime.get(slot) ?? (observedTimes.has(slot) ? null : null),
    }))
    .map((row) => ({
      slot: row.slot,
      record: recordByTime.get(row.slot) ?? null,
    }));
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

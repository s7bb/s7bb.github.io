export interface Arrival {
  train_id: string;
  line: string;
  station: string;
  direction: string;
  scheduled_time: string;
  actual_time: string | null;
  delay_minutes: number | null;
  cancelled: number; // 0 | 1 from SQLite
  reason: string | null;
}

export interface DayAggregate {
  total: number;
  on_time: number;
  late: number;
  cancelled: number;
  avg_delay_min: number;
}

export interface S7Data {
  generated_at: string;
  station: string;
  line: string;
  window_days: number;
  arrivals: Arrival[];
  aggregates: {
    today: DayAggregate;
    last_7_days: DayAggregate;
  };
}

export async function loadData(): Promise<S7Data> {
  const url = import.meta.env.DEV ? "../data/latest.json" : "./data/latest.json";
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to load data: ${resp.status}`);
  return resp.json() as Promise<S7Data>;
}

export function todayArrivals(data: S7Data): Arrival[] {
  const today = new Date().toISOString().slice(0, 10);
  return data.arrivals.filter((a) => a.scheduled_time.startsWith(today));
}

export function last7DaysByDay(data: S7Data): { date: string; avg_delay: number; cancelled: number }[] {
  const byDay = new Map<string, { delays: number[]; cancelled: number }>();
  for (const a of data.arrivals) {
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

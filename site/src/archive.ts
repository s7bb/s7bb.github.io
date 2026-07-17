import type { Arrival, DayAggregate } from "./data.js";
import { dataBase } from "./config.js";

export interface MonthSummary {
  period: string;
  finalized: boolean;
  total: number;
  on_time: number;
  late: number;
  cancelled: number;
  avg_delay_min: number;
  by_direction: Record<"muenchen" | "wolfratshausen", DayAggregate>;
}

export interface ArchiveIndex {
  generated_at: string;
  station: string;
  months: MonthSummary[];
}

export interface MonthlyArchive {
  generated_at: string;
  station: string;
  line: string;
  period: string;
  finalized: boolean;
  arrivals: Arrival[];
  aggregates: DayAggregate & {
    by_direction: Record<"muenchen" | "wolfratshausen", DayAggregate>;
  };
  daily: (DayAggregate & { date: string })[];
  daily_by_direction: Record<"muenchen" | "wolfratshausen", (DayAggregate & { date: string })[]>;
}

const _PERIOD_RE = /^\d{4}-\d{2}$/;

let _indexCache: Promise<ArchiveIndex> | null = null;
const _monthCache = new Map<string, Promise<MonthlyArchive>>();

async function archiveBase(): Promise<string> {
  return `${await dataBase()}/archive`;
}

export async function loadIndex(): Promise<ArchiveIndex> {
  if (!_indexCache) {
    _indexCache = (async () => {
      const url = `${await archiveBase()}/index.json`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`Failed to load archive index: ${resp.status}`);
      const idx = (await resp.json()) as ArchiveIndex;
      // index.json comes from the bot-writable s7bb-data repo: never let a
      // non-YYYY-MM period reach a renderer (stored-XSS containment).
      idx.months = Array.isArray(idx.months)
        ? idx.months.filter((m) => typeof m.period === "string" && _PERIOD_RE.test(m.period))
        : [];
      return idx;
    })().catch((e) => { _indexCache = null; throw e; });
  }
  return _indexCache;
}

export async function loadMonth(period: string): Promise<MonthlyArchive> {
  if (!_PERIOD_RE.test(period)) {
    throw new Error(`Invalid period: ${period}`);
  }
  let cached = _monthCache.get(period);
  if (!cached) {
    cached = (async () => {
      const url = `${await archiveBase()}/${period}.json`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`Failed to load month ${period}: ${resp.status}`);
      return resp.json() as Promise<MonthlyArchive>;
    })().catch((e) => { _monthCache.delete(period); throw e; });
    _monthCache.set(period, cached);
  }
  return cached;
}

export function _resetCache(): void {
  _indexCache = null;
  _monthCache.clear();
}

import type { Arrival, DayAggregate } from "./data.js";

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

function archiveBase(): string {
  return import.meta.env.DEV
    ? "../data/archive"
    : `${import.meta.env.BASE_URL}data/archive`;
}

export async function loadIndex(): Promise<ArchiveIndex> {
  if (!_indexCache) {
    _indexCache = (async () => {
      const url = `${archiveBase()}/index.json`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`Failed to load archive index: ${resp.status}`);
      return resp.clone().json() as Promise<ArchiveIndex>;
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
      const url = `${archiveBase()}/${period}.json`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`Failed to load month ${period}: ${resp.status}`);
      return resp.clone().json() as Promise<MonthlyArchive>;
    })().catch((e) => { _monthCache.delete(period); throw e; });
    _monthCache.set(period, cached);
  }
  return cached;
}

export function _resetCache(): void {
  _indexCache = null;
  _monthCache.clear();
}

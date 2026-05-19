import { describe, it, expect } from "vitest";
import { last7DaysByDayBothDirections } from "./data.js";
import type { S7Data, Arrival } from "./data.js";

function arrival(overrides: Partial<Arrival>): Arrival {
  return {
    train_id: "x",
    line: "S7",
    station: "Baierbrunn",
    direction: "",
    direction_bucket: "muenchen",
    scheduled_time: "2026-05-01T08:00:00",
    actual_time: null,
    delay_minutes: 0,
    cancelled: false,
    reason: null,
    train_number: null,
    ...overrides,
  };
}

function fixture(arrivals: Arrival[]): S7Data {
  return {
    generated_at: "2026-05-08T07:00:00Z",
    station: "Baierbrunn",
    line: "S7",
    window_days: 7,
    arrivals,
    aggregates: {
      today:        { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0,
        by_direction: {
          muenchen:       { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
        }},
      last_7_days:  { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0,
        by_direction: {
          muenchen:       { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
        }},
    },
    expected_slots: { today: { muenchen: [], wolfratshausen: [] } },
  };
}

describe("last7DaysByDayBothDirections", () => {
  it("returns empty array when no arrivals", () => {
    expect(last7DaysByDayBothDirections(fixture([]))).toEqual([]);
  });

  it("groups by date and direction, computing scheduled / cancelled / avg_delay", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 2, cancelled: false }),
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", delay_minutes: 4, cancelled: false }),
      arrival({ scheduled_time: "2026-05-01T10:00:00", direction_bucket: "muenchen", delay_minutes: null, cancelled: true }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "wolfratshausen", delay_minutes: 1, cancelled: false }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows).toHaveLength(1);
    expect(rows[0].date).toBe("2026-05-01");
    expect(rows[0].muenchen).toEqual({ avg_delay: 3, cancelled: 1, scheduled: 3 });
    expect(rows[0].wolfratshausen).toEqual({ avg_delay: 1, cancelled: 0, scheduled: 1 });
  });

  it("ignores arrivals with direction_bucket 'unknown'", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "unknown", delay_minutes: 99, cancelled: false }),
    ]);
    expect(last7DaysByDayBothDirections(data)).toEqual([]);
  });

  it("yields zero sub-row when one direction is absent on a date", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 5, cancelled: false }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows[0].muenchen).toEqual({ avg_delay: 5, cancelled: 0, scheduled: 1 });
    expect(rows[0].wolfratshausen).toEqual({ avg_delay: 0, cancelled: 0, scheduled: 0 });
  });

  it("returns dates ascending across multiple days", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-03T08:00:00", direction_bucket: "muenchen", delay_minutes: 1 }),
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 2 }),
      arrival({ scheduled_time: "2026-05-02T08:00:00", direction_bucket: "muenchen", delay_minutes: 3 }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows.map(r => r.date)).toEqual(["2026-05-01", "2026-05-02", "2026-05-03"]);
  });

  it("treats avg_delay as 0 when direction has only cancelled arrivals", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", cancelled: true, delay_minutes: null }),
    ]);
    expect(last7DaysByDayBothDirections(data)[0].muenchen).toEqual({ avg_delay: 0, cancelled: 1, scheduled: 1 });
  });
});

import { describe, it, expect, beforeEach } from "vitest";
import { renderWeekKpiStrip } from "./weekKpi.js";
import type { DirectionAggregate } from "../data.js";

function aggregate(over: Partial<DirectionAggregate> = {}): DirectionAggregate {
  return { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0, ...over };
}

let host: HTMLElement;

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host")!;
});

describe("renderWeekKpiStrip", () => {
  it("renders two kpi cards", () => {
    renderWeekKpiStrip(host, {
      muenchen:       aggregate({ avg_delay_min: 3.2, cancelled: 2 }),
      wolfratshausen: aggregate({ avg_delay_min: 4.1, cancelled: 1 }),
    });
    const cards = host.querySelectorAll(".kpi-card");
    expect(cards).toHaveLength(2);
  });

  it("uses singular Ausfall for cancelled === 1", () => {
    renderWeekKpiStrip(host, {
      muenchen:       aggregate({ avg_delay_min: 3.2, cancelled: 2 }),
      wolfratshausen: aggregate({ avg_delay_min: 4.1, cancelled: 1 }),
    });
    expect(host.textContent).toContain("1 Ausfall");
    expect(host.textContent).toContain("2 Ausfälle");
  });

  it("rounds avg_delay_min to 1 decimal with German comma", () => {
    renderWeekKpiStrip(host, {
      muenchen:       aggregate({ avg_delay_min: 3.247, cancelled: 0 }),
      wolfratshausen: aggregate({ avg_delay_min: 4.0,  cancelled: 0 }),
    });
    expect(host.textContent).toContain("Ø 3,2 min");
    expect(host.textContent).toContain("Ø 4,0 min");
  });

  it("includes both direction labels", () => {
    renderWeekKpiStrip(host, {
      muenchen:       aggregate(),
      wolfratshausen: aggregate(),
    });
    expect(host.textContent).toContain("München");
    expect(host.textContent).toContain("Wolfratshausen");
  });

  it("renders em-dash placeholders when aggregate is missing", () => {
    renderWeekKpiStrip(host, undefined);
    expect(host.textContent).toContain("Ø - min");
    expect(host.textContent).toContain("- Ausfälle");
  });
});

describe("hostile aggregates", () => {
  it("never injects markup and does not throw on tampered fields", () => {
    const hostile: any = {
      muenchen:       { avg_delay_min: '<img src=x onerror="window.__pwned=1">', cancelled: "<script>1</script>" },
      wolfratshausen: { avg_delay_min: 1.5, cancelled: 2 },
    };
    renderWeekKpiStrip(host, hostile);
    expect(host.querySelector("img")).toBeNull();
    expect(host.querySelector("script")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    expect(host.textContent).toContain("Ø 0,0 min");
    expect(host.textContent).toContain("Ø 1,5 min");
  });
});

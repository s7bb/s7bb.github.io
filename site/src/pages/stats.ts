import type { S7Data } from "../data.js";
import { renderStatusPie } from "../charts/statusPie.js";
import { renderAvgDelayLine } from "../charts/avgDelayLine.js";
import { last7DaysByDay } from "../data.js";

export function renderStats(data: S7Data, container: HTMLElement): void {
  const byDay = last7DaysByDay(data);
  const agg = data.aggregates.last_7_days;

  const topReasons = (() => {
    const counts = new Map<string, number>();
    for (const a of data.arrivals) {
      if (a.reason) counts.set(a.reason, (counts.get(a.reason) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  })();

  container.innerHTML = `
    <h2>Statistik — S7 Baierbrunn</h2>
    <div class="charts-grid">
      <div class="chart-box">
        <h3>Pünktlichkeit (7 Tage)</h3>
        <canvas id="chart-status-pie"></canvas>
      </div>
      <div class="chart-box">
        <h3>Ø Verspätung pro Tag</h3>
        <canvas id="chart-delay-line"></canvas>
      </div>
    </div>
    ${topReasons.length ? `
    <div class="reasons-box">
      <h3>Häufigste Gründe</h3>
      <ul>
        ${topReasons.map(([r, n]) => `<li>${r} <em>(${n}×)</em></li>`).join("")}
      </ul>
    </div>` : ""}
    <p class="data-age">Zeitraum: letzte ${data.window_days} Tage · ${agg.total} Züge erfasst</p>
  `;

  renderStatusPie("chart-status-pie", agg);
  renderAvgDelayLine("chart-delay-line", byDay);
}

import type { S7Data } from "../data.js";
import { last7DaysByDay, directionLabel, escapeHtml } from "../data.js";
import { renderStatusPie } from "../charts/statusPie.js";
import { renderAvgDelayLine } from "../charts/avgDelayLine.js";

function renderDirectionStats(data: S7Data, bucket: "muenchen" | "wolfratshausen"): string {
  const label = directionLabel(bucket);
  const agg = data.aggregates.last_7_days.by_direction[bucket];
  return `
    <div class="direction-stats">
      <h3>Richtung ${label}</h3>
      <p class="stats-summary">${agg.total} Züge · Ø ${agg.avg_delay_min} min · ${agg.missing} ohne Daten</p>
      <div class="charts-grid">
        <div class="chart-box">
          <h4>Pünktlichkeit</h4>
          <canvas id="chart-pie-${bucket}"></canvas>
        </div>
        <div class="chart-box">
          <h4>Ø Verspätung / Tag</h4>
          <canvas id="chart-line-${bucket}"></canvas>
        </div>
      </div>
    </div>`;
}

export function renderStats(data: S7Data, container: HTMLElement): void {
  const agg = data.aggregates.last_7_days;

  const topReasons = (() => {
    const counts = new Map<string, number>();
    for (const a of data.arrivals) {
      if (a.reason) counts.set(a.reason, (counts.get(a.reason) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  })();

  container.innerHTML = `
    <h2>Statistik — S7 Baierbrunn (7 Tage)</h2>
    ${renderDirectionStats(data, "muenchen")}
    <hr class="section-divider">
    ${renderDirectionStats(data, "wolfratshausen")}
    ${topReasons.length ? `
    <div class="reasons-box">
      <h3>Häufigste Gründe (alle Richtungen)</h3>
      <ul>
        ${topReasons.map(([r, n]) => `<li>${escapeHtml(r)} <em>(${n}×)</em></li>`).join("")}
      </ul>
    </div>` : ""}
    <p class="data-age">Zeitraum: letzte ${data.window_days} Tage · ${agg.total} Züge erfasst</p>
  `;

  renderStatusPie("chart-pie-muenchen", data.aggregates.last_7_days.by_direction.muenchen);
  renderAvgDelayLine("chart-line-muenchen", last7DaysByDay(data, "muenchen"));
  renderStatusPie("chart-pie-wolfratshausen", data.aggregates.last_7_days.by_direction.wolfratshausen);
  renderAvgDelayLine("chart-line-wolfratshausen", last7DaysByDay(data, "wolfratshausen"));
}

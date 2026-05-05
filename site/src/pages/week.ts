import type { S7Data } from "../data.js";
import { last7DaysByDay, directionLabel } from "../data.js";
import { renderDelayHistogram } from "../charts/delayHistogram.js";

export function renderWeek(data: S7Data, container: HTMLElement): void {
  const agg = data.aggregates.last_7_days;

  container.innerHTML = `
    <h2>Letzte 7 Tage — S7 Baierbrunn</h2>
    <div class="summary-bar">
      <span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>
      <span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>
      <span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>
      <span class="summary-item">Ø ${agg.avg_delay_min} min Verspätung</span>
    </div>
    <div class="chart-container">
      <h3>Richtung ${directionLabel("muenchen")}</h3>
      <canvas id="chart-week-muenchen"></canvas>
    </div>
    <div class="chart-container">
      <h3>Richtung ${directionLabel("wolfratshausen")}</h3>
      <canvas id="chart-week-wolfratshausen"></canvas>
    </div>
  `;

  renderDelayHistogram("chart-week-muenchen", last7DaysByDay(data, "muenchen"));
  renderDelayHistogram("chart-week-wolfratshausen", last7DaysByDay(data, "wolfratshausen"));
}

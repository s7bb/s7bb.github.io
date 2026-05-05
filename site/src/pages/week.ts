import type { S7Data } from "../data.js";
import { last7DaysByDay } from "../data.js";
import { renderDelayHistogram } from "../charts/delayHistogram.js";

export function renderWeek(data: S7Data, container: HTMLElement): void {
  const byDay = last7DaysByDay(data);
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
      <canvas id="chart-week-delay"></canvas>
    </div>
  `;

  renderDelayHistogram("chart-week-delay", byDay);
}

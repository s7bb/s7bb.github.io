import type { S7Data } from "../data.js";
import { last7DaysByDayBothDirections } from "../data.js";
import { renderWeekKpiStrip } from "../charts/weekKpi.js";
import { renderWeekDelayBars } from "../charts/weekDelayBars.js";
import { renderWeekCancellationBars } from "../charts/weekCancellationBars.js";
import { loadIndex } from "../archive.js";
import { renderMonthsBar } from "../charts/monthsBar.js";

export async function renderWeek(data: S7Data, container: HTMLElement): Promise<void> {
  const agg = data.aggregates.last_7_days.by_direction;
  const rows = last7DaysByDayBothDirections(data);

  container.innerHTML = `
    <h2>Letzte 7 Tage — S7 Baierbrunn</h2>
    <div id="week-kpi"></div>
    <div class="chart-container">
      <h3>Ø Verspätung (Minuten)</h3>
      <canvas id="chart-week-delay"></canvas>
    </div>
    <div class="chart-container">
      <h3>Ausfälle (Anzahl)</h3>
      <canvas id="chart-week-cancellations"></canvas>
    </div>
    <h3>Letzte 12 Monate</h3>
    <div class="chart-container">
      <canvas id="chart-week-months"></canvas>
    </div>
  `;

  renderWeekKpiStrip(document.getElementById("week-kpi")!, agg);
  renderWeekDelayBars("chart-week-delay", rows);
  renderWeekCancellationBars("chart-week-cancellations", rows);

  try {
    const idx = await loadIndex();
    renderMonthsBar("chart-week-months", idx.months.slice(-12));
  } catch {
    const el = document.getElementById("chart-week-months")?.parentElement;
    if (el) el.innerHTML = `<p class="error">Monatsübersicht nicht verfügbar</p>`;
  }
}

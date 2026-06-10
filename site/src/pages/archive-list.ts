import { loadIndex } from "../archive.js";
import { escapeHtml, germanMonth, num } from "../data.js";
import { renderMonthsBar } from "../charts/monthsBar.js";

export async function renderArchiveList(container: HTMLElement): Promise<void> {
  let idx;
  try {
    idx = await loadIndex();
  } catch {
    container.innerHTML = `<p class="error">Archivdaten nicht verfügbar</p>`;
    return;
  }

  const last12 = idx.months.slice(-12);

  container.innerHTML = `
    <h2>Archiv - S7 Baierbrunn</h2>
    <section class="months-overview">
      <h3>Letzte 12 Monate</h3>
      <div class="chart-container">
        <canvas id="chart-months-bar"></canvas>
      </div>
    </section>
    <section class="months-list">
      <h3>Alle Monate</h3>
      <ul class="month-links">
        ${idx.months.slice().reverse().map((m) => `
          <li>
            <a href="#archiv/${escapeHtml(m.period)}">${escapeHtml(germanMonth(m.period))}</a>
            <span class="month-summary">
              ${num(m.total)} Züge · ${num(m.on_time)} pünktlich · ${num(m.late)} verspätet · ${num(m.cancelled)} ausgefallen
              ${m.finalized ? "" : " <em>(läuft)</em>"}
            </span>
          </li>`).join("")}
      </ul>
    </section>
  `;

  renderMonthsBar("chart-months-bar", last12);
}

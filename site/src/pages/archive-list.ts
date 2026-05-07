import { loadIndex } from "../archive.js";
import { renderMonthsBar } from "../charts/monthsBar.js";

function germanMonth(period: string): string {
  const [y, m] = period.split("-");
  const months = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                  "Juli", "August", "September", "Oktober", "November", "Dezember"];
  return `${months[parseInt(m, 10)]} ${y}`;
}

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
    <h2>Archiv — S7 Baierbrunn</h2>
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
            <a href="#archiv/${m.period}">${germanMonth(m.period)}</a>
            <span class="month-summary">
              ${m.total} Züge · ${m.on_time} pünktlich · ${m.late} verspätet · ${m.cancelled} ausgefallen
              ${m.finalized ? "" : " <em>(läuft)</em>"}
            </span>
          </li>`).join("")}
      </ul>
    </section>
  `;

  renderMonthsBar("chart-months-bar", last12);
}

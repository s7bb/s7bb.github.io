import { loadMonth } from "../archive.js";
import { escapeHtml } from "../data.js";
import { renderDailyByDirection } from "../charts/dailyByDirection.js";

function germanMonth(period: string): string {
  const [y, m] = period.split("-");
  const months = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                  "Juli", "August", "September", "Oktober", "November", "Dezember"];
  return `${months[parseInt(m, 10)]} ${y}`;
}

function fmtTime(iso: string): string {
  return iso.slice(11, 16);
}

function archiveJsonUrl(period: string): string {
  return import.meta.env.DEV
    ? `../data/archive/${period}.json`
    : `${import.meta.env.BASE_URL}data/archive/${period}.json`;
}

export async function renderArchiveDetail(period: string, container: HTMLElement): Promise<void> {
  if (!/^\d{4}-\d{2}$/.test(period)) {
    container.innerHTML = `<p class="error">Ungültiger Zeitraum: ${escapeHtml(period)}</p>`;
    return;
  }

  let arc;
  try {
    arc = await loadMonth(period);
  } catch {
    container.innerHTML = `<p class="error">Archiv für ${escapeHtml(germanMonth(period))} nicht verfügbar</p>`;
    return;
  }

  const agg = arc.aggregates;

  container.innerHTML = `
    <h2>${germanMonth(period)} — S7 Baierbrunn ${arc.finalized ? "" : "<em>(läuft)</em>"}</h2>
    <div class="summary-bar">
      <span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>
      <span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>
      <span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>
      <span class="summary-item">Ø ${agg.avg_delay_min} min Verspätung</span>
    </div>
    <h3>Pünktlichkeit pro Tag</h3>
    <div class="chart-container">
      <canvas id="chart-archive-daily"></canvas>
    </div>
    <h3>Alle Ankünfte (${arc.arrivals.length})</h3>
    <div class="archive-table-wrap">
      <table class="archive-table">
        <thead>
          <tr><th>Datum</th><th>Soll</th><th>Ist</th><th>Verspätung</th><th>Richtung</th><th>Status</th></tr>
        </thead>
        <tbody>
          ${arc.arrivals.map((a) => `
            <tr>
              <td>${a.scheduled_time.slice(0, 10)}</td>
              <td>${fmtTime(a.scheduled_time)}</td>
              <td>${a.actual_time ? fmtTime(a.actual_time) : "—"}</td>
              <td>${a.delay_minutes ?? 0} min</td>
              <td>${escapeHtml(a.direction)}</td>
              <td>${a.cancelled ? "Ausgefallen" : (a.delay_minutes && a.delay_minutes > 0 ? "Verspätet" : "Pünktlich")}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <p class="data-age">
      <a href="${archiveJsonUrl(period)}" download>Rohdaten herunterladen (JSON)</a>
    </p>
  `;

  renderDailyByDirection("chart-archive-daily", arc);
}

import { loadMonth } from "../archive.js";
import { escapeHtml, germanMonth, num, terminusLabelShort } from "../data.js";
import type { Arrival } from "../data.js";
import { renderDailyByDirection } from "../charts/dailyByDirection.js";
import { dataBase } from "../config.js";

function fmtTime(iso: string): string {
  return escapeHtml(String(iso).slice(11, 16));
}

function archiveJsonUrl(base: string, period: string): string {
  return `${base}/archive/${period}.json`;
}

export function endpunktCell(a: Arrival): string {
  if (a.cancelled) {
    return `<td class="endpunkt-cell">-</td>`;
  }
  const bucket = a.direction_bucket;
  if (bucket !== "muenchen" && bucket !== "wolfratshausen") {
    return `<td class="endpunkt-cell">-</td>`;
  }
  const short = terminusLabelShort(bucket);
  switch (a.terminus_status) {
    case "arrived": {
      const m = Math.max(0, a.terminus_delay_minutes ?? 0);
      const label = m > 0 ? `${short} +${m}` : short;
      return `<td class="endpunkt-cell endpunkt--ok">${escapeHtml(label)}</td>`;
    }
    case "short_turn": {
      const st = a.terminus_short_turn_station ?? "unbekannt";
      return `<td class="endpunkt-cell endpunkt--shortturn">${escapeHtml(st)} (Kurzwende)</td>`;
    }
    case "cancelled":
      return `<td class="endpunkt-cell endpunkt--missed">nicht angekommen</td>`;
    case "pending":
    default:
      return `<td class="endpunkt-cell">-</td>`;
  }
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
  const base = await dataBase();

  container.innerHTML = `
    <h2>${escapeHtml(germanMonth(period))} - S7 Baierbrunn ${arc.finalized ? "" : "<em>(läuft)</em>"}</h2>
    <div class="summary-bar">
      <span class="summary-item summary-item--ok">✓ ${num(agg.on_time)} pünktlich</span>
      <span class="summary-item summary-item--late">⏱ ${num(agg.late)} verspätet</span>
      <span class="summary-item summary-item--cancelled">✕ ${num(agg.cancelled)} ausgefallen</span>
      <span class="summary-item">Ø ${num(agg.avg_delay_min)} min Verspätung</span>
    </div>
    <h3>Pünktlichkeit pro Tag</h3>
    <div class="chart-container">
      <canvas id="chart-archive-daily"></canvas>
    </div>
    <h3>Alle Ankünfte (${arc.arrivals.length})</h3>
    <div class="archive-table-wrap">
      <table class="archive-table">
        <thead>
          <tr><th>Datum</th><th>Soll</th><th>Ist</th><th>Verspätung</th><th>Richtung</th><th>Status</th><th class="endpunkt-cell">Endpunkt</th></tr>
        </thead>
        <tbody>
          ${arc.arrivals.map((a) => `
            <tr>
              <td>${escapeHtml(String(a.scheduled_time).slice(0, 10))}</td>
              <td>${fmtTime(a.scheduled_time)}</td>
              <td>${a.actual_time ? fmtTime(a.actual_time) : "-"}</td>
              <td>${num(a.delay_minutes)} min</td>
              <td>${escapeHtml(a.direction)}</td>
              <td>${a.cancelled ? "Ausgefallen" : (num(a.delay_minutes) > 0 ? "Verspätet" : "Pünktlich")}</td>
              ${endpunktCell(a)}
            </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <p class="data-age">
      <a href="${escapeHtml(archiveJsonUrl(base, period))}" download>Rohdaten herunterladen (JSON)</a>
    </p>
  `;

  renderDailyByDirection("chart-archive-daily", arc);
}

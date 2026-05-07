import type { S7Data } from "../data.js";
import { arrivalsByDirection, directionLabel, escapeHtml } from "../data.js";
import type { Arrival } from "../data.js";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

export function nextUpdate(generatedAt: string): Date {
  const d = new Date(generatedAt);
  d.setUTCMinutes(0, 0, 0);
  d.setUTCHours(d.getUTCHours() + 1);
  return d;
}

function statusBadge(a: Arrival): string {
  if (a.cancelled) return `<span class="badge badge--cancelled">ausgefallen</span>`;
  if ((a.delay_minutes ?? 0) > 0) return `<span class="badge badge--late">+${a.delay_minutes} min</span>`;
  return `<span class="badge badge--ok">pünktlich</span>`;
}

function renderDirectionColumn(data: S7Data, bucket: "muenchen" | "wolfratshausen"): string {
  const rows = arrivalsByDirection(data, bucket);
  const agg = data.aggregates.today.by_direction[bucket];
  const label = directionLabel(bucket);

  const summaryItems = [
    `<span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>`,
    `<span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>`,
    `<span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>`,
    agg.missing > 0 ? `<span class="summary-item summary-item--missing">? ${agg.missing} keine Daten</span>` : "",
  ].filter(Boolean).join("");

  const rowsHtml = rows.map(({ slot, record }) => {
    if (!record) {
      return `
        <div class="arrival-row arrival-row--missing">
          <span class="arrival-time">${formatTime(slot)}</span>
          <span class="arrival-line">S7</span>
          <span class="arrival-direction">—</span>
          <span class="badge badge--missing">keine Daten</span>
        </div>`;
    }
    return `
      <div class="arrival-row ${record.cancelled ? "arrival-row--cancelled" : ""}">
        <span class="arrival-time">${formatTime(record.scheduled_time)}</span>
        <span class="arrival-line">S7</span>
        <span class="arrival-direction">${escapeHtml(record.direction)}</span>
        ${statusBadge(record)}
        ${record.reason ? `<span class="arrival-reason">${escapeHtml(record.reason)}</span>` : ""}
      </div>`;
  }).join("");

  return `
    <section class="direction-col">
      <h3>Richtung ${label}</h3>
      <div class="summary-bar">${summaryItems}</div>
      <div class="arrival-list">
        ${rows.length ? rowsHtml : "<p>Keine Daten für heute.</p>"}
      </div>
    </section>`;
}

export function renderToday(data: S7Data, container: HTMLElement): void {
  const agg = data.aggregates.today;

  container.innerHTML = `
    <h2>Heute — S7 Baierbrunn</h2>
    <div class="today-grid">
      ${renderDirectionColumn(data, "muenchen")}
      ${renderDirectionColumn(data, "wolfratshausen")}
    </div>
    <details class="today-combined">
      <summary>Gesamt heute: ${agg.total} Züge · Ø ${agg.avg_delay_min} min Verspätung</summary>
    </details>
    <p class="data-age">Stand: ${new Date(data.generated_at).toLocaleString("de-DE")}</p>
  `;
}

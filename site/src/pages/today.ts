import type { S7Data, UnifiedSlotRow, DirectionAggregate } from "../data.js";
import { unifiedTodayRows, escapeHtml } from "../data.js";
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

function summaryBar(agg: DirectionAggregate): string {
  return [
    `<span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>`,
    `<span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>`,
    `<span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>`,
    agg.missing > 0 ? `<span class="summary-item summary-item--missing">? ${agg.missing} keine Daten</span>` : "",
  ].filter(Boolean).join("");
}

function rowFor(slot: string, a: Arrival | null): string {
  const time = formatTime(slot);
  if (!a) {
    return `
      <div class="arrival-row arrival-row--empty">
        <span class="arrival-time">${time}</span>
        <span class="arrival-empty">—</span>
      </div>`;
  }
  const cancelledCls = a.cancelled ? " arrival-row--cancelled" : "";
  return `
    <div class="arrival-row${cancelledCls}">
      <span class="arrival-time">${time}</span>
      <span class="arrival-direction">${escapeHtml(a.direction)}</span>
      ${statusBadge(a)}
      ${a.reason ? `<span class="arrival-reason">${escapeHtml(a.reason)}</span>` : ""}
    </div>`;
}

function renderRows(rows: UnifiedSlotRow[]): string {
  // Two cells per slot in row-major order so the outer 2-col grid pairs
  // München (left) and Wolfratshausen (right) at the same vertical row.
  return rows
    .map((r) => rowFor(r.slot, r.muenchen) + rowFor(r.slot, r.wolfratshausen))
    .join("");
}

export function renderToday(data: S7Data, container: HTMLElement): void {
  const agg = data.aggregates.today;
  const rows = unifiedTodayRows(data);

  container.innerHTML = `
    <h2>Heute — S7 Baierbrunn</h2>
    <div class="today-grid">
      <div class="direction-col">
        <h3>Richtung München</h3>
        <div class="summary-bar">${summaryBar(agg.by_direction.muenchen)}</div>
      </div>
      <div class="direction-col">
        <h3>Richtung Wolfratshausen</h3>
        <div class="summary-bar">${summaryBar(agg.by_direction.wolfratshausen)}</div>
      </div>
    </div>
    ${rows.length
      ? `<div class="today-rows">${renderRows(rows)}</div>`
      : `<p>Keine Daten für heute.</p>`}
    <details class="today-combined">
      <summary>Gesamt heute: ${agg.total} Züge · Ø ${agg.avg_delay_min} min Verspätung</summary>
    </details>
    <p class="data-age">Stand: ${new Date(data.generated_at).toLocaleString("de-DE")} · Nächstes Update: ${formatTime(nextUpdate(data.generated_at).toISOString())}</p>
  `;
}

import type { Arrival, S7Data } from "../data.js";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

function statusBadge(a: Arrival): string {
  if (a.cancelled) return `<span class="badge badge--cancelled">ausgefallen</span>`;
  if ((a.delay_minutes ?? 0) > 0) return `<span class="badge badge--late">+${a.delay_minutes} min</span>`;
  return `<span class="badge badge--ok">pünktlich</span>`;
}

export function renderToday(data: S7Data, container: HTMLElement): void {
  const today = new Date().toISOString().slice(0, 10);
  const arrivals = data.arrivals
    .filter((a) => a.scheduled_time.startsWith(today))
    .sort((a, b) => a.scheduled_time.localeCompare(b.scheduled_time));

  const agg = data.aggregates.today;

  const summary = `
    <div class="summary-bar">
      <span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>
      <span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>
      <span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>
      ${agg.avg_delay_min > 0 ? `<span class="summary-item">Ø ${agg.avg_delay_min} min Verspätung</span>` : ""}
    </div>`;

  const rows = arrivals.map((a) => `
    <div class="arrival-row ${a.cancelled ? "arrival-row--cancelled" : ""}">
      <span class="arrival-time">${formatTime(a.scheduled_time)}</span>
      <span class="arrival-line">S7</span>
      <span class="arrival-direction">${a.direction}</span>
      ${statusBadge(a)}
      ${a.reason ? `<span class="arrival-reason">${a.reason}</span>` : ""}
    </div>
  `).join("");

  container.innerHTML = `
    <h2>Heute — S7 Baierbrunn</h2>
    ${summary}
    <div class="arrival-list">
      ${arrivals.length ? rows : "<p>Keine Daten für heute.</p>"}
    </div>
    <p class="data-age">Stand: ${new Date(data.generated_at).toLocaleString("de-DE")}</p>
  `;
}

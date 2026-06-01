import type { S7Data, UnifiedSlotRow, DirectionAggregate, TerminusAggregate } from "../data.js";
import { unifiedTodayRows, escapeHtml, terminusLabelLong, terminusLabelShort, terminusAggregate } from "../data.js";
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

// Terminus badge: same shape + palette as the departure status badge.
// Silent for null terminus_status (no data) and for Baierbrunn-cancelled
// (departure badge already says "ausgefallen"). Full detail is in the panel.
function terminusLine(a: Arrival): string {
  if (a.cancelled) return "";
  switch (a.terminus_status) {
    case "arrived": {
      const m = Math.max(0, a.terminus_delay_minutes ?? 0);
      if (m > 0) return `<span class="badge badge--late">+${m} min</span>`;
      return `<span class="badge badge--ok">pünktlich</span>`;
    }
    case "short_turn":
      if (!a.terminus_short_turn_station) {
        console.warn("terminus_status=short_turn with null station for train", a.train_id);
        return `<span class="badge badge--cancelled">ausgefallen</span>`;
      }
      return `<span class="badge badge--late">Kurzwende</span>`;
    case "cancelled":
      return `<span class="badge badge--cancelled">ausgefallen</span>`;
    case "pending":
      return `<span class="badge badge--missing">unterwegs</span>`;
    default:
      return "";
  }
}

function statusBadge(a: Arrival): string {
  if (a.cancelled) return `<span class="badge badge--cancelled">ausgefallen</span>`;
  if ((a.delay_minutes ?? 0) > 0) return `<span class="badge badge--late">+${a.delay_minutes} min</span>`;
  return `<span class="badge badge--ok">pünktlich</span>`;
}

function fmtDeparture(a: Arrival): string {
  if (a.cancelled) return "ausgefallen";
  const t = formatTime(a.scheduled_time);
  const m = a.delay_minutes ?? 0;
  if (m > 0) return `${t} (+${m} min)`;
  return `${t} (planmäßig)`;
}

function fmtTerminusArrival(a: Arrival): string {
  // arrived: HH:MM (+N min) with N = floor(terminus_delay_minutes, 0), or "planmäßig" if null.
  // cancelled: "nicht angekommen". pending: "noch unterwegs".
  switch (a.terminus_status) {
    case "arrived": {
      const m = a.terminus_delay_minutes;
      if (m === null || m === undefined) return "planmäßig";
      const floored = Math.max(0, m);
      // No reliable terminus actual_time on Arrival - show delay only (matches spec example for null-actual case, generalised).
      const sched = formatTime(a.scheduled_time);
      // Compute display-only arrival time by adding scheduled departure offset - we don't have it.
      // Per spec the value examples include "07:17 (+3 min)"; spec note says when terminus_delay_minutes is null we display "planmäßig" only.
      // The Arrival type does not currently carry a terminus actual time; show "(+N min)" without computed HH:MM, prefixed by Soll-Ankunft? Spec ambiguous; we render delay only since no terminus actual exists in the data model.
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      void sched;
      return floored > 0 ? `+${floored} min` : `+0 min`;
    }
    case "short_turn":
    case "cancelled":
      return "nicht angekommen";
    case "pending":
      return "noch unterwegs";
    default:
      return "";
  }
}

function detailRow(label: string, value: string): string {
  return `<div class="detail-row"><span class="detail-label">${escapeHtml(label)}:</span><span class="detail-value">${escapeHtml(value)}</span></div>`;
}

function detailRowsInner(a: Arrival): string {
  const rows: string[] = [];
  rows.push(detailRow("Abfahrt Baierbrunn", fmtDeparture(a)));

  if (a.cancelled) {
    if (!a.reason) {
      rows.push(`<div class="detail-row detail-row--note">Zug ausgefallen - keine Fahrt</div>`);
    }
  } else if (a.terminus_status) {
    const long = a.direction_bucket === "muenchen" || a.direction_bucket === "wolfratshausen"
      ? terminusLabelLong(a.direction_bucket)
      : "";
    rows.push(detailRow(`Ankunft ${long}`, fmtTerminusArrival(a)));
  }

  if (a.terminus_status === "short_turn" && a.terminus_short_turn_station) {
    rows.push(detailRow("Endete in", `${a.terminus_short_turn_station} (Kurzwende)`));
  }
  if (a.train_number) {
    rows.push(detailRow("Zug", `S ${a.train_number}`));
  }
  if (a.reason) {
    rows.push(detailRow("Grund", a.reason));
  }
  return rows.join("");
}

function summaryBar(
  agg: DirectionAggregate,
  term: TerminusAggregate,
  bucket: "muenchen" | "wolfratshausen",
): string {
  const showTerm = term.arrived + term.short_turn + term.missed > 0;
  const termItems = showTerm
    ? [
        term.arrived > 0
          ? `<span class="summary-item summary-item--ok">✓ ${term.arrived} bis ${terminusLabelShort(bucket)}</span>`
          : "",
        term.short_turn > 0
          ? `<span class="summary-item summary-item--shortturn">⚠ ${term.short_turn} Kurzwende</span>`
          : "",
        term.missed > 0
          ? `<span class="summary-item summary-item--missed">⊘ ${term.missed} nicht angekommen</span>`
          : "",
      ]
    : [];
  return [
    `<span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>`,
    `<span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>`,
    `<span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>`,
    agg.missing > 0 ? `<span class="summary-item summary-item--missing">? ${agg.missing} keine Daten</span>` : "",
    ...termItems,
  ].filter(Boolean).join("");
}

function slotKey(slot: string, bucket: "muenchen" | "wolfratshausen"): string {
  return `slot-${bucket}-${slot.replace(/[^0-9]/g, "")}`;
}

type RowParts = { summary: string; detail: string };

function rowFor(slot: string, a: Arrival | null, bucket: "muenchen" | "wolfratshausen"): RowParts {
  const time = formatTime(slot);
  if (!a) {
    return {
      summary: `<div class="arrival-row arrival-row--empty"><span class="arrival-time">${time}</span><span class="arrival-empty">-</span></div>`,
      detail: "",
    };
  }
  const id = slotKey(slot, bucket);
  const cancelledCls = a.cancelled ? " arrival-row--cancelled" : "";
  const summary = `<button type="button" class="arrival-row${cancelledCls}" aria-expanded="false" aria-controls="${id}" data-detail="${id}">` +
    `<span class="arrival-time">${time}</span>` +
    `<span class="arrival-direction">${escapeHtml(a.direction)}</span>` +
    `<span class="badge-slot badge-slot--dep">${statusBadge(a)}</span>` +
    `<span class="badge-slot badge-slot--term">${terminusLine(a)}</span>` +
    `<span class="chev" aria-hidden="true"></span>` +
    `</button>`;
  const detail = `<div class="arrival-detail" id="${id}" hidden>${detailRowsInner(a)}</div>`;
  return { summary, detail };
}

function renderRows(rows: UnifiedSlotRow[]): string {
  // Per-slot pair: both summary cells in row 1, both detail panels in
  // subsequent rows spanning the full pair width. Open panel escapes its
  // column so values are not clipped on mobile.
  return rows
    .map((r) => {
      const m = rowFor(r.slot, r.muenchen, "muenchen");
      const w = rowFor(r.slot, r.wolfratshausen, "wolfratshausen");
      return `<div class="slot-pair">${m.summary}${w.summary}${m.detail}${w.detail}</div>`;
    })
    .join("");
}

function wireDetailToggles(container: HTMLElement): void {
  const rowsEl = container.querySelector(".today-rows");
  if (!rowsEl) return;
  rowsEl.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest("button.arrival-row") as HTMLButtonElement | null;
    if (!btn) return;
    const id = btn.getAttribute("data-detail");
    if (!id) return;
    const panel = container.querySelector(`#${id}`) as HTMLElement | null;
    if (!panel) return;
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", open ? "false" : "true");
    panel.hidden = open;
  });
}

export function renderToday(data: S7Data, container: HTMLElement): void {
  const agg = data.aggregates.today;
  const rows = unifiedTodayRows(data);
  const termM = terminusAggregate(data.arrivals, "muenchen");
  const termW = terminusAggregate(data.arrivals, "wolfratshausen");

  container.innerHTML = `
    <h2>Heute - S7 Baierbrunn</h2>
    <div class="today-grid">
      <div class="direction-col">
        <h3>Richtung München</h3>
        <div class="summary-bar">${summaryBar(agg.by_direction.muenchen, termM, "muenchen")}</div>
      </div>
      <div class="direction-col">
        <h3>Richtung Wolfratshausen</h3>
        <div class="summary-bar">${summaryBar(agg.by_direction.wolfratshausen, termW, "wolfratshausen")}</div>
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
  wireDetailToggles(container);
}

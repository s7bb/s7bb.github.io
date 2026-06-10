import { num, type DirectionAggregate } from "../data.js";

type KpiInput =
  | { muenchen: DirectionAggregate; wolfratshausen: DirectionAggregate }
  | undefined;

function ausfallWord(n: number): string {
  return n === 1 ? "Ausfall" : "Ausfälle";
}

function formatMin(n: number): string {
  return n.toFixed(1).replace(".", ",");
}

function cardHtml(label: string, agg: DirectionAggregate | undefined): string {
  if (!agg) {
    return `
      <div class="kpi-card">
        <div class="kpi-card__title">→ ${label}</div>
        <div class="kpi-card__stats">Ø - min · - Ausfälle</div>
      </div>
    `;
  }
  const cancelled = num(agg.cancelled);
  return `
    <div class="kpi-card">
      <div class="kpi-card__title">→ ${label}</div>
      <div class="kpi-card__stats">Ø ${formatMin(num(agg.avg_delay_min))} min · ${cancelled} ${ausfallWord(cancelled)}</div>
    </div>
  `;
}

export function renderWeekKpiStrip(container: HTMLElement, agg: KpiInput): void {
  container.innerHTML = `
    <div class="kpi-strip">
      ${cardHtml("München",        agg?.muenchen)}
      ${cardHtml("Wolfratshausen", agg?.wolfratshausen)}
    </div>
  `;
}

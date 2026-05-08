import {
  Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend,
  type ChartConfiguration, type TooltipItem,
} from "chart.js";
import type { DayDirRow } from "../data.js";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

const COLOR_MUENCHEN = "#006ab3";
const COLOR_WOLFRATSHAUSEN = "#6c4fc4";

function formatDay(dateIso: string): string {
  const dt = new Date(dateIso);
  return dt.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });
}

export function formatCancellationTooltip(direction: string, n: number, scheduled: number): string {
  const word = n === 1 ? "Ausfall" : "Ausfälle";
  const pct = scheduled === 0 ? 0 : Math.round((n / scheduled) * 100);
  return `${direction}: ${n} ${word} (${n} von ${scheduled} geplant, ${pct} %)`;
}

export function buildCancellationChartConfig(rows: DayDirRow[]): ChartConfiguration<"bar"> {
  const labels = rows.map(r => formatDay(r.date));
  const muData = rows.map(r => r.muenchen.cancelled);
  const woData = rows.map(r => r.wolfratshausen.cancelled);
  const muScheduled = rows.map(r => r.muenchen.scheduled);
  const woScheduled = rows.map(r => r.wolfratshausen.scheduled);

  return {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "München",        data: muData, backgroundColor: COLOR_MUENCHEN },
        { label: "Wolfratshausen", data: woData, backgroundColor: COLOR_WOLFRATSHAUSEN },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: "top" },
        tooltip: {
          callbacks: {
            label: (item: TooltipItem<"bar">) => {
              const direction = item.dataset.label ?? "";
              const n = item.parsed.y;
              const scheduled = item.datasetIndex === 0 ? muScheduled[item.dataIndex] : woScheduled[item.dataIndex];
              return formatCancellationTooltip(direction, n, scheduled);
            },
          },
        },
      },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 } },
      },
    },
  };
}

export function renderWeekCancellationBars(canvasId: string, rows: DayDirRow[]): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  Chart.getChart(canvas)?.destroy();
  new Chart(canvas, buildCancellationChartConfig(rows));
}

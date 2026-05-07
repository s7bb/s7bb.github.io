import { Chart, registerables } from "chart.js";
import type { MonthSummary } from "../archive.js";

Chart.register(...registerables);

export function renderMonthsBar(canvasId: string, months: MonthSummary[]): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const labels = months.map((m) => m.period);
  const onTime    = months.map((m) => m.on_time);
  const late      = months.map((m) => m.late);
  const cancelled = months.map((m) => m.cancelled);

  new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Pünktlich",    data: onTime,    backgroundColor: "#2e7d32", stack: "s" },
        { label: "Verspätet",    data: late,      backgroundColor: "#f9a825", stack: "s" },
        { label: "Ausgefallen",  data: cancelled, backgroundColor: "#c62828", stack: "s" },
      ],
    },
    options: {
      responsive: true,
      onClick: (_evt, elements) => {
        if (!elements.length) return;
        const i = elements[0].index;
        location.hash = `#/archiv/${labels[i]}`;
      },
      plugins: { legend: { position: "bottom" } },
      scales: {
        x: { stacked: true },
        y: { stacked: true, beginAtZero: true },
      },
    },
  });
}

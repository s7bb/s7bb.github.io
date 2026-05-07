import { Chart, registerables } from "chart.js";
import type { MonthlyArchive } from "../archive.js";

Chart.register(...registerables);

type DailyRow = MonthlyArchive["daily_by_direction"]["muenchen"][number];

function onTimePercent(d: DailyRow): number {
  return d.total > 0 ? (d.on_time / d.total) * 100 : 0;
}

export function renderDailyByDirection(canvasId: string, archive: MonthlyArchive): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const m = archive.daily_by_direction.muenchen;
  const w = archive.daily_by_direction.wolfratshausen;
  const labels = Array.from(new Set([...m.map(d => d.date), ...w.map(d => d.date)])).sort();

  const byDate = (rows: DailyRow[]) =>
    new Map(rows.map((r) => [r.date, r]));
  const mMap = byDate(m);
  const wMap = byDate(w);

  new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "München (Pünktlich %)",
          data: labels.map((d) => mMap.has(d) ? onTimePercent(mMap.get(d)!) : null),
          borderColor: "#1565c0",
          spanGaps: true,
        },
        {
          label: "Wolfratshausen (Pünktlich %)",
          data: labels.map((d) => wMap.has(d) ? onTimePercent(wMap.get(d)!) : null),
          borderColor: "#6a1b9a",
          spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { position: "bottom" } },
      scales: { y: { beginAtZero: true, max: 100, ticks: { callback: (v) => `${v}%` } } },
    },
  });
}

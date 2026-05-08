import {
  Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend,
  type ChartConfiguration, type Plugin, type TooltipItem,
} from "chart.js";
import type { DayDirRow } from "../data.js";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

const COLOR_MUENCHEN = "#006ab3";
const COLOR_WOLFRATSHAUSEN = "#6c4fc4";
const COLOR_BAND_GREEN = "rgba(34,197,94,0.10)";
const COLOR_BAND_RED   = "rgba(239,68,68,0.08)";

export const PUNCTUALITY_THRESHOLD_MIN = 6;

function formatDay(dateIso: string): string {
  const dt = new Date(dateIso);
  return dt.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export const punctualityBandPlugin: Plugin<"bar"> = {
  id: "punctualityBand",
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea } = chart;
    const yScale = chart.scales.y;
    if (!yScale) return;
    const top = chartArea.top;
    const bottom = chartArea.bottom;
    const left = chartArea.left;
    const right = chartArea.right;
    const yMaxData = yScale.max;
    const thresholdY = yScale.getPixelForValue(Math.min(PUNCTUALITY_THRESHOLD_MIN, yMaxData));

    ctx.save();
    ctx.fillStyle = COLOR_BAND_GREEN;
    ctx.fillRect(left, thresholdY, right - left, bottom - thresholdY);

    if (yMaxData > PUNCTUALITY_THRESHOLD_MIN) {
      ctx.fillStyle = COLOR_BAND_RED;
      ctx.fillRect(left, top, right - left, thresholdY - top);
    }
    ctx.restore();
  },
};

export function buildDelayChartConfig(rows: DayDirRow[]): ChartConfiguration<"bar"> {
  const labels = rows.map(r => formatDay(r.date));
  const muData = rows.map(r => round1(r.muenchen.avg_delay));
  const woData = rows.map(r => round1(r.wolfratshausen.avg_delay));

  return {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "München",        data: muData, backgroundColor: COLOR_MUENCHEN },
        { label: "Wolfratshausen", data: woData, backgroundColor: COLOR_WOLFRATSHAUSEN },
      ],
    },
    plugins: [punctualityBandPlugin],
    options: {
      responsive: true,
      plugins: {
        legend: { position: "top" },
        tooltip: {
          callbacks: {
            label: (item: TooltipItem<"bar">) =>
              `${item.dataset.label}: Ø ${item.parsed.y.toFixed(1)} min`,
          },
        },
      },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "Minuten" } },
      },
    },
  };
}

export function renderWeekDelayBars(canvasId: string, rows: DayDirRow[]): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  Chart.getChart(canvas)?.destroy();
  new Chart(canvas, buildDelayChartConfig(rows));
}

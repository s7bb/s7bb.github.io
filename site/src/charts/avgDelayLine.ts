import { Chart, LineController, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Legend } from "chart.js";

Chart.register(LineController, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Legend);

export function renderAvgDelayLine(
  canvasId: string,
  data: { date: string; avg_delay: number; cancelled: number }[],
): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  Chart.getChart(canvas)?.destroy();

  const labels = data.map((d) => {
    const dt = new Date(d.date);
    return dt.toLocaleDateString("de-DE", { weekday: "short", day: "numeric" });
  });

  new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Ø Verspätung (min)",
          data: data.map((d) => Math.round(d.avg_delay * 10) / 10),
          borderColor: "rgba(255, 159, 64, 1)",
          backgroundColor: "rgba(255, 159, 64, 0.1)",
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, title: { display: true, text: "Minuten" } } },
    },
  });
}

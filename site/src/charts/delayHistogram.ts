import { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend } from "chart.js";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

export function renderDelayHistogram(
  canvasId: string,
  data: { date: string; avg_delay: number; cancelled: number }[],
): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;

  const labels = data.map((d) => {
    const dt = new Date(d.date);
    return dt.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });
  });

  new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Ø Verspätung (min)",
          data: data.map((d) => Math.round(d.avg_delay * 10) / 10),
          backgroundColor: "rgba(255, 159, 64, 0.8)",
        },
        {
          label: "Ausfälle",
          data: data.map((d) => d.cancelled),
          backgroundColor: "rgba(255, 99, 132, 0.8)",
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { position: "top" } },
      scales: { y: { beginAtZero: true } },
    },
  });
}

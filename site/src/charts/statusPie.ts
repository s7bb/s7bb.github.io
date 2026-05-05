import { Chart, PieController, ArcElement, Tooltip, Legend } from "chart.js";
import type { DayAggregate } from "../data.js";

Chart.register(PieController, ArcElement, Tooltip, Legend);

export function renderStatusPie(canvasId: string, agg: DayAggregate): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;

  new Chart(canvas, {
    type: "pie",
    data: {
      labels: ["Pünktlich", "Verspätet", "Ausgefallen"],
      datasets: [
        {
          data: [agg.on_time, agg.late, agg.cancelled],
          backgroundColor: [
            "rgba(75, 192, 92, 0.8)",
            "rgba(255, 159, 64, 0.8)",
            "rgba(255, 99, 132, 0.8)",
          ],
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { position: "right" } },
    },
  });
}

import "./style.css";
import { loadData } from "./data.js";
import { renderToday } from "./pages/today.js";
import { renderWeek } from "./pages/week.js";
import { renderStats } from "./pages/stats.js";
import { renderMethodology } from "./pages/methodology.js";

type PageId = "heute" | "woche" | "statistik" | "methodik";

const pages: Record<PageId, (data: unknown, el: HTMLElement) => void> = {
  heute: (d, el) => renderToday(d as Parameters<typeof renderToday>[0], el),
  woche: (d, el) => renderWeek(d as Parameters<typeof renderWeek>[0], el),
  statistik: (d, el) => renderStats(d as Parameters<typeof renderStats>[0], el),
  methodik: (_d, el) => renderMethodology(el),
};

async function main() {
  const content = document.getElementById("content")!;
  const nav = document.getElementById("nav")!;

  let currentData: Awaited<ReturnType<typeof loadData>> | null = null;

  async function getData() {
    if (!currentData) currentData = await loadData();
    return currentData;
  }

  async function showPage(id: PageId) {
    content.innerHTML = `<p class="loading">Lade Daten…</p>`;
    nav.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.page === id));
    try {
      const data = id === "methodik" ? null : await getData();
      content.innerHTML = "";
      pages[id](data!, content);
    } catch (e) {
      content.innerHTML = `<p class="error">Fehler beim Laden der Daten. Bitte später nochmal versuchen.</p>`;
      console.error(e);
    }
  }

  nav.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;
    if (target.tagName === "A" && target.dataset.page) {
      e.preventDefault();
      const page = target.dataset.page as PageId;
      history.pushState({ page }, "", `#${page}`);
      void showPage(page);
    }
  });

  window.addEventListener("popstate", (e: PopStateEvent) => {
    const page = (e.state as { page?: PageId } | null)?.page ?? "heute";
    void showPage(page);
  });

  const initial = (location.hash.slice(1) as PageId) || "heute";
  void showPage(initial);
}

void main();

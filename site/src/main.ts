import "./style.css";
import { loadData } from "./data.js";
import { renderToday } from "./pages/today.js";
import { renderWeek } from "./pages/week.js";
import { renderStats } from "./pages/stats.js";
import { renderMethodology } from "./pages/methodology.js";
import { renderArchiveList } from "./pages/archive-list.js";
import { renderArchiveDetail } from "./pages/archive-detail.js";

type PageId = "heute" | "woche" | "statistik" | "archiv" | "methodik";

interface Route {
  page: PageId;
  period?: string;
}

const PAGE_IDS: PageId[] = ["heute", "woche", "statistik", "archiv", "methodik"];

function parseRoute(hash: string): Route {
  const h = hash.replace(/^#\/?/, "");
  if (h.startsWith("archiv/")) {
    return { page: "archiv", period: h.slice("archiv/".length) };
  }
  if ((PAGE_IDS as string[]).includes(h)) {
    return { page: h as PageId };
  }
  return { page: "heute" };
}

async function main() {
  const content = document.getElementById("content")!;
  const nav = document.getElementById("nav")!;

  let liveData: Awaited<ReturnType<typeof loadData>> | null = null;
  async function getLiveData() {
    if (!liveData) liveData = await loadData();
    return liveData;
  }

  async function renderRoute(route: Route): Promise<void> {
    nav.querySelectorAll("a").forEach((a) =>
      a.classList.toggle("active", a.dataset.page === route.page),
    );
    content.innerHTML = `<p class="loading">Lade Daten…</p>`;

    try {
      if (route.page === "archiv") {
        if (route.period) {
          await renderArchiveDetail(route.period, content);
        } else {
          await renderArchiveList(content);
        }
        return;
      }
      if (route.page === "methodik") {
        content.innerHTML = "";
        renderMethodology(content);
        return;
      }
      const data = await getLiveData();
      content.innerHTML = "";
      switch (route.page) {
        case "heute":     renderToday(data, content); break;
        case "woche":     await renderWeek(data, content); break;
        case "statistik": renderStats(data, content); break;
      }
    } catch (e) {
      console.error(e);
      content.innerHTML = `<p class="error">Fehler beim Laden der Daten. Bitte später nochmal versuchen.</p>`;
    }
  }

  function navigate() {
    void renderRoute(parseRoute(location.hash));
  }

  window.addEventListener("hashchange", navigate);

  navigate();
}

void main();

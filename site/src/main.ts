import "./style.css";
import { loadData } from "./data.js";
import { renderToday } from "./pages/today.js";
import { renderWeek } from "./pages/week.js";
import { renderStats } from "./pages/stats.js";
import { renderMethodology } from "./pages/methodology.js";
import { renderArchiveList } from "./pages/archive-list.js";
import { renderArchiveDetail } from "./pages/archive-detail.js";

type LivePage = "heute" | "woche" | "statistik" | "methodik";

interface Route {
  section: "live" | "archiv";
  livePage?: LivePage;
  period?: string;
}

function parseRoute(hash: string): Route {
  const h = hash.replace(/^#\/?/, "");
  if (h.startsWith("archiv/")) {
    const period = h.slice("archiv/".length);
    return { section: "archiv", period };
  }
  if (h === "archiv") return { section: "archiv" };
  if (h === "" || h === "live") return { section: "live", livePage: "heute" };
  if (["heute", "woche", "statistik", "methodik"].includes(h)) {
    return { section: "live", livePage: h as LivePage };
  }
  return { section: "live", livePage: "heute" };
}

const liveTabs: { id: LivePage; label: string }[] = [
  { id: "heute",     label: "Heute" },
  { id: "woche",     label: "Letzte 7 Tage" },
  { id: "statistik", label: "Statistik" },
  { id: "methodik",  label: "Methodik" },
];

function renderSubNav(route: Route): void {
  const subnav = document.getElementById("sub-nav")!;
  if (route.section === "live") {
    subnav.innerHTML = liveTabs
      .map((t) => `<a href="#${t.id}" data-page="${t.id}">${t.label}</a>`)
      .join("");
    subnav.querySelectorAll("a").forEach((a) =>
      a.classList.toggle("active", a.dataset.page === route.livePage),
    );
    subnav.style.display = "";
  } else {
    subnav.innerHTML = "";
    subnav.style.display = "none";
  }
}

async function main() {
  const content = document.getElementById("content")!;
  const topNav = document.getElementById("top-nav")!;

  let liveData: Awaited<ReturnType<typeof loadData>> | null = null;
  async function getLiveData() {
    if (!liveData) liveData = await loadData();
    return liveData;
  }

  async function renderRoute(route: Route): Promise<void> {
    topNav.querySelectorAll("a").forEach((a) =>
      a.classList.toggle("active", a.dataset.section === route.section),
    );
    renderSubNav(route);
    content.innerHTML = `<p class="loading">Lade Daten…</p>`;

    try {
      if (route.section === "archiv") {
        if (route.period) {
          await renderArchiveDetail(route.period, content);
        } else {
          await renderArchiveList(content);
        }
        return;
      }
      const data = await getLiveData();
      content.innerHTML = "";
      switch (route.livePage) {
        case "heute":     renderToday(data, content); break;
        case "woche":     await renderWeek(data, content); break;
        case "statistik": renderStats(data, content); break;
        case "methodik":  renderMethodology(content); break;
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

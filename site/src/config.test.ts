import { describe, it, expect, beforeEach, vi } from "vitest";
import { resolveBase, dataBase, _resetConfigCache } from "./config.js";

beforeEach(() => {
  _resetConfigCache();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("resolveBase", () => {
  const dflt = { configValue: undefined, viteValue: undefined, dev: false, baseUrl: "/" };

  it("prefers config.json over everything", () => {
    expect(resolveBase({ ...dflt, configValue: "https://cdn.example/d", viteValue: "/vite" }))
      .toBe("https://cdn.example/d");
  });

  it("falls back to the vite var when config is absent", () => {
    expect(resolveBase({ ...dflt, viteValue: "/vite" })).toBe("/vite");
  });

  it("falls back to the built-in default in prod", () => {
    expect(resolveBase(dflt)).toBe("/data");
  });

  it("falls back to the relative path in dev", () => {
    expect(resolveBase({ ...dflt, dev: true })).toBe("../data");
  });

  it("ignores a non-string config value", () => {
    expect(resolveBase({ ...dflt, configValue: 42 })).toBe("/data");
  });

  it("ignores an empty or whitespace config value", () => {
    expect(resolveBase({ ...dflt, configValue: "   " })).toBe("/data");
  });

  it("strips a trailing slash so callers can always append /latest.json", () => {
    expect(resolveBase({ ...dflt, configValue: "https://cdn.example/d/" }))
      .toBe("https://cdn.example/d");
  });

  it("respects a non-root baseUrl", () => {
    expect(resolveBase({ ...dflt, baseUrl: "/s7bb/" })).toBe("/s7bb/data");
  });
});

// These exercise dataBase() end to end. Vitest sets import.meta.env.DEV = true, so
// every fallback here resolves to the dev path "../data".
describe("dataBase", () => {
  it("uses dataBaseUrl from config.json when present", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ dataBaseUrl: "https://cdn.example/d" }), { status: 200 }) as Response,
    );
    expect(await dataBase()).toBe("https://cdn.example/d");
  });

  it("falls back silently when config.json is missing", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("not found", { status: 404 }) as Response,
    );
    expect(await dataBase()).toBe("../data");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("falls back silently when config.json is not JSON", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<!doctype html><html></html>", { status: 200 }) as Response,
    );
    expect(await dataBase()).toBe("../data");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("falls back silently when the fetch itself rejects", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network down"));
    expect(await dataBase()).toBe("../data");
  });

  it("fetches config.json only once across calls", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ dataBaseUrl: "/data" }), { status: 200 }) as Response,
    );
    await dataBase();
    await dataBase();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("warns when config.json is unreadable in a production build", async () => {
    vi.stubEnv("DEV", false);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("not found", { status: 404 }) as Response,
    );
    expect(await dataBase()).toBe("/data");
    expect(warnSpy).toHaveBeenCalledOnce();
  });

  it("does not warn in a production build when config.json is readable", async () => {
    vi.stubEnv("DEV", false);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ dataBaseUrl: "https://cdn.example/d" }), { status: 200 }) as Response,
    );
    expect(await dataBase()).toBe("https://cdn.example/d");
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

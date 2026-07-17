// Resolves where the site reads its JSON from.
//
// The base URL is a runtime setting: the container entrypoint writes
// config.json at startup, so switching data source needs a restart, not a
// rebuild. Falls back to the build-time default when no config.json exists,
// which is the normal case for `npm run dev` and the dev compose profile.
//
// VITE_DATA_BASE_URL is a build-time escape hatch for anyone building the
// bundle outside Docker. Nothing in this repo sets it; the container uses
// config.json instead.

export interface BaseSources {
  configValue: unknown;
  viteValue: string | undefined;
  dev: boolean;
  baseUrl: string;
}

function stripTrailingSlash(u: string): string {
  return u.endsWith("/") ? u.slice(0, -1) : u;
}

function usable(v: unknown): v is string {
  return typeof v === "string" && v.trim() !== "";
}

export function resolveBase(s: BaseSources): string {
  if (usable(s.configValue)) return stripTrailingSlash(s.configValue.trim());
  if (usable(s.viteValue)) return stripTrailingSlash(s.viteValue.trim());
  return s.dev ? "../data" : stripTrailingSlash(`${s.baseUrl}data`);
}

let _baseCache: Promise<string> | null = null;

export function _resetConfigCache(): void {
  _baseCache = null;
}

// Test helper: set the base without a config.json round-trip. Tests that mock
// fetch with a single shared Response need this, otherwise dataBase() drains
// the body before the code under test can read it.
export function _primeDataBase(base: string): void {
  _baseCache = Promise.resolve(base);
}

export function dataBase(): Promise<string> {
  if (!_baseCache) {
    _baseCache = (async () => {
      let configValue: unknown;
      try {
        const resp = await fetch(`${import.meta.env.BASE_URL}config.json`);
        if (resp.ok) {
          const cfg = (await resp.json()) as { dataBaseUrl?: unknown };
          configValue = cfg?.dataBaseUrl;
        }
      } catch {
        // No config.json, or it is not JSON. Normal in dev and in a plain
        // `npm run preview`. Fall through to the build-time default; this is
        // not an error and must not be logged as one.
      }
      return resolveBase({
        configValue,
        viteValue: import.meta.env.VITE_DATA_BASE_URL as string | undefined,
        dev: import.meta.env.DEV,
        baseUrl: import.meta.env.BASE_URL,
      });
    })();
  }
  return _baseCache;
}

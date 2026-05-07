import { describe, it, expect } from "vitest";
import { nextUpdate } from "./today.js";

describe("nextUpdate", () => {
  it("returns next top of hour when generated_at is exactly on the hour", () => {
    expect(nextUpdate("2026-05-07T14:00:00Z").toISOString()).toBe("2026-05-07T15:00:00.000Z");
  });

  it("returns next top of hour when generated_at is mid-hour", () => {
    expect(nextUpdate("2026-05-07T14:00:30Z").toISOString()).toBe("2026-05-07T15:00:00.000Z");
  });

  it("returns next top of hour when generated_at is at end of hour", () => {
    expect(nextUpdate("2026-05-07T14:59:59Z").toISOString()).toBe("2026-05-07T15:00:00.000Z");
  });

  it("rolls over to next day at 23:xx", () => {
    expect(nextUpdate("2026-05-07T23:30:00Z").toISOString()).toBe("2026-05-08T00:00:00.000Z");
  });
});

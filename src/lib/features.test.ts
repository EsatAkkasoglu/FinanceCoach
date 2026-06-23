import { describe, expect, it } from "vitest";
import { isNavEnabled } from "./features";

describe("isNavEnabled", () => {
  it("hides the deferred surfaces from the primary nav", () => {
    expect(isNavEnabled("/budget")).toBe(false);
    expect(isNavEnabled("/documents")).toBe(false);
  });

  it("keeps the hero-loop surfaces enabled", () => {
    for (const p of ["/chat", "/dashboard", "/portfolio", "/funds", "/discover", "/goals", "/settings"]) {
      expect(isNavEnabled(p)).toBe(true);
    }
  });

  it("defaults unknown paths to enabled", () => {
    expect(isNavEnabled("/something-new")).toBe(true);
  });
});

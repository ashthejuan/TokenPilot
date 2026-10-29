import { describe, expect, it } from "vitest";

import { parseThresholdNumber, retentionBeforeParam } from "@/lib/settings";

describe("retentionBeforeParam", () => {
  it("reads a datetime-local value as UTC", () => {
    expect(retentionBeforeParam("2026-06-01T00:00")).toBe("2026-06-01T00:00:00.000Z");
  });

  it("passes aware offsets through, normalized to UTC", () => {
    expect(retentionBeforeParam("2026-06-01T02:00+02:00")).toBe("2026-06-01T00:00:00.000Z");
  });

  it("returns null for empty or invalid input", () => {
    expect(retentionBeforeParam("")).toBeNull();
    expect(retentionBeforeParam("not-a-date")).toBeNull();
  });
});

describe("parseThresholdNumber", () => {
  it("parses finite numbers", () => {
    expect(parseThresholdNumber("300")).toBe(300);
    expect(parseThresholdNumber("0.5")).toBe(0.5);
  });

  it("returns null for blank or non-numeric input", () => {
    expect(parseThresholdNumber("")).toBeNull();
    expect(parseThresholdNumber("abc")).toBeNull();
    expect(parseThresholdNumber("Infinity")).toBeNull();
  });
});

import { describe, expect, it } from "vitest";

import { parseThresholdNumber, retentionBeforeParam } from "@/lib/settings";

describe("retentionBeforeParam", () => {
  it("converts a datetime-local value to a UTC Z bound", () => {
    const param = retentionBeforeParam("2026-06-01T00:00");

    expect(param).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$/);
    expect(param === null ? null : Date.parse(param)).toBe(
      new Date("2026-06-01T00:00").getTime(),
    );
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

import { describe, expect, it } from "vitest";

import { formatReportPeriod } from "@/lib/reports";

describe("formatReportPeriod", () => {
  it("labels open bounds explicitly", () => {
    expect(formatReportPeriod({ from: null, to: null })).toBe("start of ledger → now");
  });

  it("formats closed bounds as UTC timestamps", () => {
    const label = formatReportPeriod({
      from: "2026-10-01T00:00:00.000Z",
      to: "2026-10-30T00:00:00.000Z",
    });
    expect(label).toContain("→");
    expect(label).not.toContain("start of ledger");
    expect(label).not.toContain("now");
  });
});

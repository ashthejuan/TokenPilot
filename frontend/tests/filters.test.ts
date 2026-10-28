import { describe, expect, it } from "vitest";

import { DEFAULT_FILTERS, summaryParams } from "@/lib/filters";

const NOW = new Date("2026-10-28T12:00:00.000Z");

describe("summaryParams", () => {
  it("maps presets to a from bound and a bucket", () => {
    expect(summaryParams({ ...DEFAULT_FILTERS, range: "24h" }, NOW)).toEqual({
      from: "2026-10-27T12:00:00.000Z",
      bucket: "hour",
    });
    expect(summaryParams({ ...DEFAULT_FILTERS, range: "30d" }, NOW)).toEqual({
      from: "2026-09-28T12:00:00.000Z",
      bucket: "day",
    });
  });

  it("passes only the dimension filters that are set", () => {
    expect(
      summaryParams(
        { ...DEFAULT_FILTERS, range: "7d", projectId: "p1", provider: "meta", modelId: "", outcome: "failed" },
        NOW,
      ),
    ).toEqual({
      from: "2026-10-21T12:00:00.000Z",
      bucket: "day",
      project_id: "p1",
      provider: "meta",
      outcome: "failed",
    });
  });

  it("sends a custom range as UTC bounds, hourly when short", () => {
    const params = summaryParams(
      {
        ...DEFAULT_FILTERS,
        range: "custom",
        customFrom: "2026-10-27T00:00:00.000Z",
        customTo: "2026-10-28T00:00:00.000Z",
      },
      NOW,
    );
    expect(params).toEqual({
      from: "2026-10-27T00:00:00.000Z",
      to: "2026-10-28T00:00:00.000Z",
      bucket: "hour",
    });
  });

  it("returns null for a custom range that ends before it starts", () => {
    expect(
      summaryParams(
        {
          ...DEFAULT_FILTERS,
          range: "custom",
          customFrom: "2026-10-28T00:00:00.000Z",
          customTo: "2026-10-27T00:00:00.000Z",
        },
        NOW,
      ),
    ).toBeNull();
  });
});

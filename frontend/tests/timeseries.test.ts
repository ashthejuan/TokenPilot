import { describe, expect, it } from "vitest";

import { padTimeseries } from "@/lib/timeseries";

describe("padTimeseries", () => {
  it("fills empty day buckets across the selected range so a single day stays a thin slot", () => {
    const padded = padTimeseries(
      [
        {
          bucket_start: "2026-10-30T00:00:00.000Z",
          estimated_cost: 0.000065,
          currency: "USD",
          request_count: 2,
        },
      ],
      {
        bucket: "day",
        from: "2026-10-24T12:00:00.000Z",
        to: "2026-10-30T18:00:00.000Z",
      },
    );

    expect(padded.map((p) => p.bucket_start)).toEqual([
      "2026-10-24T00:00:00.000Z",
      "2026-10-25T00:00:00.000Z",
      "2026-10-26T00:00:00.000Z",
      "2026-10-27T00:00:00.000Z",
      "2026-10-28T00:00:00.000Z",
      "2026-10-29T00:00:00.000Z",
      "2026-10-30T00:00:00.000Z",
    ]);
    expect(padded[0]).toEqual({
      bucket_start: "2026-10-24T00:00:00.000Z",
      estimated_cost: 0,
      currency: "USD",
      request_count: 0,
    });
    expect(padded[6]).toEqual({
      bucket_start: "2026-10-30T00:00:00.000Z",
      estimated_cost: 0.000065,
      currency: "USD",
      request_count: 2,
    });
  });

  it("fills empty hour buckets for a short range", () => {
    const padded = padTimeseries(
      [
        {
          bucket_start: "2026-10-30T14:00:00.000Z",
          estimated_cost: 0.01,
          currency: "USD",
          request_count: 1,
        },
      ],
      {
        bucket: "hour",
        from: "2026-10-30T12:30:00.000Z",
        to: "2026-10-30T15:10:00.000Z",
      },
    );

    expect(padded.map((p) => p.bucket_start)).toEqual([
      "2026-10-30T12:00:00.000Z",
      "2026-10-30T13:00:00.000Z",
      "2026-10-30T14:00:00.000Z",
      "2026-10-30T15:00:00.000Z",
    ]);
    expect(padded[2].estimated_cost).toBe(0.01);
    expect(padded[0].request_count).toBe(0);
  });

  it("returns an empty list when there are no points", () => {
    expect(
      padTimeseries([], {
        bucket: "day",
        from: "2026-10-24T00:00:00.000Z",
        to: "2026-10-30T00:00:00.000Z",
      }),
    ).toEqual([]);
  });
});

import { describe, expect, it } from "vitest";

import {
  latestComparison,
  savingsBadgeKind,
  savingsBadgeLabel,
  type ComparisonOut,
} from "@/lib/benchmarks";

function comparisonFixture(overrides: Partial<ComparisonOut>): ComparisonOut {
  return {
    id: "cmp-1",
    benchmark_id: "bench-1",
    baseline_variant: "baseline",
    alternative_variant: "targeted-context",
    baseline_run_id: "run-base",
    alternative_run_id: "run-alt",
    cost_delta: 0.18,
    cost_delta_pct: "60.0",
    correctness_preserved: true,
    comparison_status: "verified",
    methodology: {},
    reasons: [],
    created_at: "2026-10-28T00:00:02.000Z",
    ...overrides,
  };
}

describe("savingsBadgeLabel", () => {
  it("labels cheaper-but-incorrect as not an optimization", () => {
    expect(
      savingsBadgeLabel({ status: "measured", correctness_preserved: false, cost_delta: 0.1 }),
    ).toBe("Not an optimization");
  });

  it("labels verified as verified savings", () => {
    expect(
      savingsBadgeLabel({ status: "verified", correctness_preserved: true, cost_delta: 0.18 }),
    ).toBe("Verified savings");
  });

  it("labels measured-and-correct as measured savings", () => {
    expect(
      savingsBadgeLabel({ status: "measured", correctness_preserved: true, cost_delta: 0.05 }),
    ).toBe("Measured savings");
  });

  it("labels measured with unknown correctness as measured savings", () => {
    expect(
      savingsBadgeLabel({ status: "measured", correctness_preserved: null, cost_delta: null }),
    ).toBe("Measured savings");
  });

  it("labels correctness-preserving-but-unseparated as measured savings", () => {
    expect(
      savingsBadgeLabel({
        status: "correctness_preserving",
        correctness_preserved: true,
        cost_delta: 0.02,
      }),
    ).toBe("Measured savings");
  });

  it("labels inconclusive and incomparable distinctly", () => {
    expect(
      savingsBadgeLabel({ status: "inconclusive", correctness_preserved: null, cost_delta: null }),
    ).toBe("Inconclusive");
    expect(
      savingsBadgeLabel({ status: "incomparable", correctness_preserved: null, cost_delta: null }),
    ).toBe("Incomparable");
  });

  it("labels the pre-comparison state as potential savings", () => {
    expect(
      savingsBadgeLabel({ status: "potential", correctness_preserved: null, cost_delta: null }),
    ).toBe("Potential savings");
  });
});

describe("savingsBadgeKind", () => {
  it("maps labels to badge kinds", () => {
    expect(
      savingsBadgeKind({ status: "verified", correctness_preserved: true, cost_delta: 0.18 }),
    ).toBe("verified");
    expect(
      savingsBadgeKind({ status: "measured", correctness_preserved: false, cost_delta: 0.1 }),
    ).toBe("not_optimization");
    expect(
      savingsBadgeKind({ status: "measured", correctness_preserved: true, cost_delta: 0.05 }),
    ).toBe("measured");
    expect(
      savingsBadgeKind({ status: "inconclusive", correctness_preserved: null, cost_delta: null }),
    ).toBe("inconclusive");
    expect(
      savingsBadgeKind({ status: "potential", correctness_preserved: null, cost_delta: null }),
    ).toBe("potential");
  });
});

describe("latestComparison", () => {
  it("returns null when no comparison exists", () => {
    expect(latestComparison([])).toBeNull();
  });

  it("returns the first row of the newest-first list", () => {
    const older = comparisonFixture({ id: "cmp-old", comparison_status: "measured" });
    const newer = comparisonFixture({ id: "cmp-new", comparison_status: "verified" });

    expect(latestComparison([newer, older])).toBe(newer);
  });
});

import { describe, expect, it } from "vitest";

import {
  acceptanceCommandError,
  buildAcceptanceConfig,
  eligibleRuns,
  latestComparison,
  parseRequiredPassLines,
  savingsBadgeKind,
  savingsBadgeLabel,
  splitCommandArgv,
  type BenchmarkRunOut,
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

  it("labels metrics-only measured comparisons as observational cost delta", () => {
    expect(
      savingsBadgeLabel({
        status: "measured",
        correctness_preserved: null,
        cost_delta: 0.05,
        observational: true,
      }),
    ).toBe("Observational cost delta");
    expect(
      savingsBadgeLabel({
        status: "measured",
        correctness_preserved: null,
        cost_delta: -0.01,
        observational: true,
      }),
    ).toBe("Observational — no savings");
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

  it("labels a costlier-but-correct alternative as no savings", () => {
    expect(
      savingsBadgeLabel({ status: "measured", correctness_preserved: true, cost_delta: -0.05 }),
    ).toBe("No savings");
    expect(
      savingsBadgeLabel({
        status: "correctness_preserving",
        correctness_preserved: true,
        cost_delta: -0.05,
      }),
    ).toBe("No savings");
  });

  it("labels measured-but-incorrect as not an optimization even when costlier", () => {
    expect(
      savingsBadgeLabel({ status: "measured", correctness_preserved: false, cost_delta: -0.05 }),
    ).toBe("Not an optimization");
    expect(
      savingsBadgeLabel({ status: "measured", correctness_preserved: false, cost_delta: 0 }),
    ).toBe("Not an optimization");
  });

  it("labels a zero delta as no savings and keeps a null delta as measured", () => {
    expect(
      savingsBadgeLabel({ status: "measured", correctness_preserved: true, cost_delta: 0 }),
    ).toBe("No savings");
    expect(
      savingsBadgeLabel({ status: "measured", correctness_preserved: true, cost_delta: null }),
    ).toBe("Measured savings");
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

function runFixture(overrides: Partial<BenchmarkRunOut>): BenchmarkRunOut {
  return {
    id: "run-1",
    benchmark_id: "bench-1",
    variant_name: "baseline",
    model_id: "fake-large",
    config: {},
    run_status: "completed",
    outcome: "passed",
    total_cost: 0.3,
    currency: "USD",
    unknown_cost_events: 0,
    total_tokens: 100,
    request_count: 4,
    retry_count: 0,
    duration_ms: 1000,
    test_exit_code: 0,
    test_results: null,
    patch_path: null,
    worktree_path: null,
    started_at: null,
    completed_at: null,
    repeat_index: 0,
    error: null,
    eligible: true,
    ...overrides,
  };
}

describe("splitCommandArgv", () => {
  it("splits on whitespace and ignores empty input", () => {
    expect(splitCommandArgv("python -m pytest -q")).toEqual([
      "python",
      "-m",
      "pytest",
      "-q",
    ]);
    expect(splitCommandArgv("  npm   test  ")).toEqual(["npm", "test"]);
    expect(splitCommandArgv("")).toEqual([]);
    expect(splitCommandArgv("   ")).toEqual([]);
  });
});

describe("parseRequiredPassLines", () => {
  it("returns one trimmed nodeid per non-empty line", () => {
    expect(parseRequiredPassLines("tests/a.py::test_one\n\n  tests/b.py::test_two  ")).toEqual([
      "tests/a.py::test_one",
      "tests/b.py::test_two",
    ]);
  });
});

describe("acceptanceCommandError", () => {
  it("requires a command string in command mode only", () => {
    expect(acceptanceCommandError("command", "")).toBe("Acceptance command is required.");
    expect(acceptanceCommandError("command", "   ")).toBe("Acceptance command is required.");
    expect(acceptanceCommandError("command", "pytest -q")).toBeNull();
    expect(acceptanceCommandError("metrics_only", "")).toBeNull();
  });
});

describe("buildAcceptanceConfig", () => {
  it("builds command-mode acceptance from form fields", () => {
    expect(
      buildAcceptanceConfig({
        mode: "command",
        commandText: "python -m pytest -q",
        requiredPassText: "tests/foo.py::test_bar",
        minSuccessRateText: "0.8",
      }),
    ).toEqual({
      mode: "command",
      command: ["python", "-m", "pytest", "-q"],
      required_pass: ["tests/foo.py::test_bar"],
      min_success_rate: 0.8,
    });
  });

  it("posts metrics-only acceptance without command fields", () => {
    expect(
      buildAcceptanceConfig({
        mode: "metrics_only",
        commandText: "ignored",
        requiredPassText: "ignored",
        minSuccessRateText: "0.5",
      }),
    ).toEqual({
      mode: "metrics_only",
      command: [],
      required_pass: [],
      min_success_rate: 1,
    });
  });

  it("returns an error when command mode has no command", () => {
    expect(
      buildAcceptanceConfig({
        mode: "command",
        commandText: "  ",
        requiredPassText: "",
        minSuccessRateText: "1",
      }),
    ).toEqual({ error: "Acceptance command is required." });
  });
});

describe("eligibleRuns", () => {
  it("keeps completed cost-eligible runs and drops active, cancelled, and inconclusive ones", () => {
    const runs = [
      runFixture({ id: "a", outcome: "passed" }),
      runFixture({ id: "b", outcome: "failed" }),
      runFixture({ id: "c", outcome: "timed_out" }),
      runFixture({ id: "d", outcome: "observational" }),
      runFixture({ id: "e", outcome: "cancelled" }),
      runFixture({ id: "f", outcome: "inconclusive" }),
      runFixture({ id: "g", run_status: "running", outcome: null }),
      runFixture({ id: "h", run_status: "queued", outcome: null }),
    ];

    expect(eligibleRuns(runs).map((run) => run.id)).toEqual(["a", "b", "c", "d"]);
  });
});

import { describe, expect, it } from "vitest";

import {
  buildInsightBenchmarkCreateBody,
  formatReportPeriod,
  suggestTaskSpecPath,
} from "@/lib/reports";

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

describe("create-benchmark body (no vacuous DEFAULT task_spec)", () => {
  it("requires a non-empty task_spec_path", () => {
    expect(() => buildInsightBenchmarkCreateBody("")).toThrow(/task_spec_path/i);
    expect(() => buildInsightBenchmarkCreateBody("   ")).toThrow(/task_spec_path/i);
  });

  it("posts only task_spec_path (never empty required_pass inline spec)", () => {
    const body = buildInsightBenchmarkCreateBody("/repo/demo/benchmark_task.yaml");
    expect(body).toEqual({ task_spec_path: "/repo/demo/benchmark_task.yaml" });
    expect(body).not.toHaveProperty("task_spec");
  });

  it("suggests demo/benchmark_task.yaml under a repository path", () => {
    expect(suggestTaskSpecPath("/abs/project")).toBe("/abs/project/demo/benchmark_task.yaml");
    expect(suggestTaskSpecPath("/abs/project/")).toBe("/abs/project/demo/benchmark_task.yaml");
    expect(suggestTaskSpecPath(null)).toBe("");
  });
});

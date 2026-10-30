import type { components } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/format";

export type ProjectReport = components["schemas"]["ProjectReport"];
export type SavingsReport = components["schemas"]["SavingsReport"];
export type ReportPeriod = components["schemas"]["ReportPeriod"];
export type InsightBenchmarkCreate = components["schemas"]["InsightBenchmarkCreate"];

/** Human-readable period bounds; open ends stay explicit. */
export function formatReportPeriod(period: ReportPeriod): string {
  const from = period.from ? formatTimestamp(period.from) : "start of ledger";
  const to = period.to ? formatTimestamp(period.to) : "now";
  return `${from} → ${to}`;
}

/** Suggest a demo offline task spec path under a project repository. */
export function suggestTaskSpecPath(repositoryPath: string | null | undefined): string {
  if (!repositoryPath?.trim()) return "";
  const trimmed = repositoryPath.trim().replace(/\/+$/, "");
  return `${trimmed}/demo/benchmark_task.yaml`;
}

/**
 * Body for insight → benchmark create. Requires a real task_spec_path;
 * never invents an empty required_pass / empty context_files inline spec.
 */
export function buildInsightBenchmarkCreateBody(taskSpecPath: string): InsightBenchmarkCreate {
  const path = taskSpecPath.trim();
  if (!path) {
    throw new Error("task_spec_path is required");
  }
  return { task_spec_path: path };
}

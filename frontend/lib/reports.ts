import type { components } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/format";

export type ProjectReport = components["schemas"]["ProjectReport"];
export type SavingsReport = components["schemas"]["SavingsReport"];
export type ReportPeriod = components["schemas"]["ReportPeriod"];

/** Compact default task_spec for insight → benchmark (matches demo/benchmark_task.yaml fields). */
export const DEFAULT_INSIGHT_TASK_SPEC = {
  name: "insight-benchmark",
  description: "Benchmark created from an insight recommendation.",
  task_prompt:
    "Reproduce the issue described by the insight recommendation, apply the suggested change, and make the acceptance tests pass. Do not change any tests.",
  initial_ref: "main",
  acceptance: {
    command: ["python", "-m", "pytest", "-q"],
    required_pass: [],
    min_success_rate: 1.0,
  },
  timeout_s: 300,
  repeat_count: 1,
  baseline: {
    model_id: "muse-spark-1.3",
    context_strategy: "full_repo" as const,
    max_steps: 12,
    prompt_template: "fix_v1",
  },
  alternatives: [
    {
      name: "targeted-context",
      changes: { context_strategy: "targeted" },
      context_files: [],
    },
  ],
};

/** Human-readable period bounds; open ends stay explicit. */
export function formatReportPeriod(period: ReportPeriod): string {
  const from = period.from ? formatTimestamp(period.from) : "start of ledger";
  const to = period.to ? formatTimestamp(period.to) : "now";
  return `${from} → ${to}`;
}

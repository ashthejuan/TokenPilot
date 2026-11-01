import type { components } from "@/lib/api-types";

export type BenchmarkOut = components["schemas"]["BenchmarkOut"];
export type BenchmarkDetail = components["schemas"]["BenchmarkDetail"];
export type BenchmarkRunOut = components["schemas"]["BenchmarkRunOut"];
export type RunOutcome = NonNullable<BenchmarkRunOut["outcome"]>;
export type ComparisonOut = components["schemas"]["ComparisonOut"];
export type Project = components["schemas"]["Project"];

/** Comparison status plus the pre-comparison state, which has no backend row yet. */
export type SavingsStatus = ComparisonOut["comparison_status"] | "potential";

export type SavingsKind =
  | "potential"
  | "measured"
  | "verified"
  | "not_optimization"
  | "inconclusive";

export type SavingsInput = {
  status: SavingsStatus;
  correctness_preserved: boolean | null;
  cost_delta: number | null;
  /** Metrics-only acceptance: cost delta without a pass/fail gate. */
  observational?: boolean;
};

/**
 * Badge label for a savings classification. `correctness_preserving` (correct
 * but cost ranges overlap) is measured savings that never reached verified;
 * a measured result that broke correctness is not an optimization at all.
 */
export function savingsBadgeLabel(input: SavingsInput): string {
  switch (input.status) {
    case "verified":
      return "Verified savings";
    case "measured":
    case "correctness_preserving":
      // A broken-correctness result is never an optimization, whatever it cost.
      if (input.correctness_preserved === false) return "Not an optimization";
      if (input.observational) {
        if (input.cost_delta !== null && input.cost_delta <= 0) {
          return "Observational — no savings";
        }
        return "Observational cost delta";
      }
      // A correct result that costs as much or more measured no savings.
      if (input.cost_delta !== null && input.cost_delta <= 0) return "No savings";
      return "Measured savings";
    case "inconclusive":
      return "Inconclusive";
    case "incomparable":
      return "Incomparable";
    case "potential":
      return "Potential savings";
  }
}

export function savingsBadgeKind(input: SavingsInput): SavingsKind {
  switch (input.status) {
    case "verified":
      return "verified";
    case "measured":
    case "correctness_preserving":
      return input.correctness_preserved === false ? "not_optimization" : "measured";
    case "inconclusive":
    case "incomparable":
      return "inconclusive";
    case "potential":
      return "potential";
  }
}

export function isRunActive(run: Pick<BenchmarkRunOut, "run_status">): boolean {
  return run.run_status === "queued" || run.run_status === "running";
}

/** Backend `METRICS_ONLY_REASON` — listed on metrics-only comparisons. */
export const METRICS_ONLY_REASON = "metrics-only: no acceptance tests";

const COST_ELIGIBLE_OUTCOMES: RunOutcome[] = [
  "passed",
  "failed",
  "timed_out",
  "observational",
];

/**
 * Runs that contribute to comparison cost totals: completed with a
 * cost-eligible outcome (scored or observational).
 * Mirrors backend `cost_eligible_runs` in `metrics.py`.
 */
export function eligibleRuns(runs: BenchmarkRunOut[]): BenchmarkRunOut[] {
  return runs.filter(
    (run) =>
      run.run_status === "completed" &&
      run.outcome !== null &&
      COST_ELIGIBLE_OUTCOMES.includes(run.outcome),
  );
}

export function runOutcomeLabel(outcome: BenchmarkRunOut["outcome"]): string {
  if (outcome === null) return "—";
  switch (outcome) {
    case "observational":
      return "Observational";
    case "passed":
      return "Passed";
    case "failed":
      return "Failed";
    case "timed_out":
      return "Timed out";
    case "cancelled":
      return "Cancelled";
    case "inconclusive":
      return "Inconclusive";
  }
}

/** True when the comparison is cost-only (no acceptance verification). */
export function isMetricsOnlyComparison(
  comparison: ComparisonOut,
  options?: { runs?: BenchmarkRunOut[]; acceptanceMode?: AcceptanceMode },
): boolean {
  const reasons = comparison.reasons ?? [];
  if (reasons.some((reason) => reason.includes("metrics-only"))) return true;
  if (options?.acceptanceMode === "metrics_only") return true;
  if (options?.runs?.some((run) => run.outcome === "observational")) return true;
  return (
    comparison.comparison_status === "measured" &&
    comparison.correctness_preserved === null &&
    reasons.length > 0
  );
}

export function metricsOnlyReasonInList(reasons: string[]): boolean {
  return reasons.some((reason) => reason.includes("metrics-only"));
}

export type BenchmarkStatus = "empty" | "running" | "done";

/** Derive the list-page status from a benchmark's runs. */
export function benchmarkStatus(runs: Pick<BenchmarkRunOut, "run_status">[]): BenchmarkStatus {
  if (runs.length === 0) return "empty";
  return runs.some(isRunActive) ? "running" : "done";
}

/**
 * Latest persisted comparison. The list endpoint returns rows newest-first,
 * so the head is the latest; null when the benchmark was never compared.
 */
export function latestComparison(comparisons: ComparisonOut[]): ComparisonOut | null {
  return comparisons[0] ?? null;
}

/** Direct download link for a run's patch, served through the API proxy as text. */
export function patchHref(runId: string): string {
  return `/api/tp/api/v1/benchmark-runs/${encodeURIComponent(runId)}/patch`;
}

export function formatDurationMs(value: number | null): string {
  if (value === null) return "Unknown";
  if (value < 1000) return `${value}ms`;
  const totalSeconds = Math.floor(value / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 60) {
    const seconds = totalSeconds % 60;
    return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
}

/** Sum known parts; unknown only when every part is unknown. */
export function sumNullable(...parts: (number | null)[]): number | null {
  const known = parts.filter((part): part is number => part !== null);
  if (known.length === 0) return null;
  return known.reduce((sum, part) => sum + part, 0);
}

type Methodology = ComparisonOut["methodology"];

export function methodologyStrings(methodology: Methodology, key: string): string[] {
  const value: unknown = methodology[key];
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string");
}

export function methodologyNumber(
  methodology: Methodology,
  key: string,
  field: string,
): number | null {
  const value: unknown = methodology[key];
  if (typeof value !== "object" || value === null) return null;
  const entry: unknown = (value as Record<string, unknown>)[field];
  return typeof entry === "number" ? entry : null;
}

export function methodologyFlag(methodology: Methodology, key: string): boolean {
  return methodology[key] === true;
}

export function variablesChangedLabel(variables: string[]): string {
  if (variables.length === 0) return "Variables changed: none detected";
  return `Variables changed: ${variables.join(", ")}`;
}

export type AcceptanceMode = NonNullable<
  components["schemas"]["AcceptanceConfig"]["mode"]
>;
export type AcceptanceConfig = components["schemas"]["AcceptanceConfig"];

export type BuildAcceptanceInput = {
  mode: AcceptanceMode;
  commandText: string;
  requiredPassText: string;
  minSuccessRateText: string;
};

export function parseRequiredPassLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

export function splitCommandArgv(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  return trimmed.split(/\s+/);
}

/** Client-side guard before POST in command mode. */
export function acceptanceCommandError(
  mode: AcceptanceMode,
  commandText: string,
): string | null {
  if (mode === "command" && commandText.trim().length === 0) {
    return "Acceptance command is required.";
  }
  return null;
}

export function buildAcceptanceConfig(
  input: BuildAcceptanceInput,
): AcceptanceConfig | { error: string } {
  const commandError = acceptanceCommandError(input.mode, input.commandText);
  if (commandError) return { error: commandError };

  if (input.mode === "metrics_only") {
    return {
      mode: "metrics_only",
      command: [],
      required_pass: [],
      min_success_rate: 1,
    };
  }

  const minRate = Number.parseFloat(input.minSuccessRateText);
  if (!Number.isFinite(minRate) || minRate < 0 || minRate > 1) {
    return { error: "Min success rate must be a number between 0 and 1." };
  }

  return {
    mode: "command",
    command: splitCommandArgv(input.commandText),
    required_pass: parseRequiredPassLines(input.requiredPassText),
    min_success_rate: minRate,
  };
}

import type { components } from "@/lib/api-types";

export type BenchmarkOut = components["schemas"]["BenchmarkOut"];
export type BenchmarkDetail = components["schemas"]["BenchmarkDetail"];
export type BenchmarkRunOut = components["schemas"]["BenchmarkRunOut"];
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
      return input.correctness_preserved === false ? "Not an optimization" : "Measured savings";
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

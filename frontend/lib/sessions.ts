import type { components } from "@/lib/api-types";

type InsightOut = components["schemas"]["InsightOut"];

export function formatTokens(n: number | null): string {
  if (n === null) return "unknown";
  return new Intl.NumberFormat("en-US").format(n);
}

export function retryChipLabel(e: {
  retry_group_id: string | null;
  attempt: number | null;
  retry_source: string | null;
}): string | null {
  if (e.retry_group_id === null) return null;
  const attemptPart = e.attempt !== null ? ` · attempt ${e.attempt}` : "";
  const sourcePart = e.retry_source ? ` (${e.retry_source})` : "";
  return `retry${attemptPart}${sourcePart}`;
}

export function eventsTruncated(requestCount: number, shown: number): boolean {
  return requestCount > shown;
}

export function contextSignals(insights: InsightOut[]): InsightOut[] {
  return insights.filter((insight) => insight.rule_id === "repeated_context");
}

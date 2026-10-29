import type { components } from "@/lib/api-types";

type InsightOut = components["schemas"]["InsightOut"];
type SessionOutcome = components["schemas"]["SessionUpdate"]["outcome"];

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

/** Gate stale in-flight list fetches after the effect cleans up (filter change). */
export function shouldCommitFetch(cancelled: boolean): boolean {
  return !cancelled;
}

/** Select value while a PATCH may still be awaiting parent refetch. */
export function outcomeSelectValue(
  serverOutcome: SessionOutcome,
  pendingOutcome: SessionOutcome | null,
): SessionOutcome {
  return pendingOutcome ?? serverOutcome;
}

/** Drop pending once the server prop matches; keep it while refetch lags. */
export function reconcilePendingOutcome(
  serverOutcome: SessionOutcome,
  pendingOutcome: SessionOutcome | null,
): SessionOutcome | null {
  if (pendingOutcome === null) return null;
  if (serverOutcome === pendingOutcome) return null;
  return pendingOutcome;
}

import { ApiError, apiGet } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { formatMoney } from "@/lib/format";

type EvidenceRefOut = components["schemas"]["EvidenceRefOut"];
type ResolvedEvidence = components["schemas"]["ResolvedEvidence"];
type JobOut = components["schemas"]["JobOut"];

export function evidenceHref(ref: EvidenceRefOut, row: ResolvedEvidence): string | null {
  if (!row.resolved) return null;
  if (ref.kind === "usage_event") {
    const sessionId = row.event?.session_id;
    if (!sessionId) return null;
    return `/sessions/${sessionId}#event-${row.event?.id ?? ref.id}`;
  }
  if (ref.kind === "session") {
    return `/sessions/${ref.id}`;
  }
  return null;
}

export function ruleLabel(ruleId: string, ruleVersion: number): string {
  return `${ruleId}.v${ruleVersion}`;
}

export function impactLabel(amount: number | null, currency: string | null): string {
  if (amount === null) return "Potential: unknown";
  return `Potential: ${formatMoney(amount, currency)}`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function pollJob(
  id: string,
  options: { intervalMs: number; timeoutMs: number } = { intervalMs: 1000, timeoutMs: 60000 },
): Promise<JobOut> {
  const deadline = Date.now() + options.timeoutMs;
  while (Date.now() < deadline) {
    const job = await apiGet<JobOut>(`api/v1/jobs/${id}`);
    if (job.status === "succeeded" || job.status === "failed") {
      return job;
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) break;
    await sleep(Math.min(options.intervalMs, remaining));
  }
  throw new ApiError("job_timeout", `Job ${id} timed out`, 408);
}

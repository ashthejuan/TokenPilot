import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { evidenceHref, impactLabel, pollJob, ruleLabel } from "@/lib/insights";

type EvidenceRefOut = components["schemas"]["EvidenceRefOut"];
type ResolvedEvidence = components["schemas"]["ResolvedEvidence"];
type UsageEvent = components["schemas"]["UsageEvent"];
type JobOut = components["schemas"]["JobOut"];

function event(partial: Partial<UsageEvent> = {}): UsageEvent {
  return {
    attempt: null,
    benchmark_run_id: null,
    cached_tokens: null,
    completed_at: null,
    error_category: null,
    http_status: null,
    id: "evt-1",
    idempotency_key: "key-1",
    input_tokens: 100,
    latency_ms: null,
    metadata: {},
    model_id: "fake-small",
    output_tokens: 10,
    project_id: null,
    provider: "fake",
    reasoning_tokens: null,
    request_fingerprint: null,
    retry_group_id: null,
    retry_source: null,
    session_id: "sess-1",
    source_event_id: null,
    started_at: "2026-10-27T10:00:00Z",
    status: "success",
    task_id: null,
    usage_source: "provider",
    ...partial,
  };
}

function row(partial: Partial<ResolvedEvidence> & Pick<ResolvedEvidence, "ref">): ResolvedEvidence {
  return {
    resolved: true,
    event: null,
    session: null,
    task: null,
    ...partial,
  };
}

function job(partial: Partial<JobOut> = {}): JobOut {
  return {
    created_at: "2026-10-27T10:00:00Z",
    error: null,
    finished_at: null,
    id: "job-1",
    kind: "analyze",
    params: {},
    result: null,
    started_at: null,
    status: "queued",
    ...partial,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("evidenceHref", () => {
  it("usage_event evidence links to session anchor", () => {
    const ref: EvidenceRefOut = {
      id: "evt-1",
      kind: "usage_event",
      measurement: {},
    };
    const resolved = row({ ref, event: event({ id: "evt-1", session_id: "sess-1" }) });
    expect(evidenceHref(ref, resolved)).toBe("/sessions/sess-1#event-evt-1");
  });

  it("sessionless event has no link", () => {
    const ref: EvidenceRefOut = {
      id: "evt-2",
      kind: "usage_event",
      measurement: {},
    };
    const resolved = row({
      ref,
      event: event({ id: "evt-2", session_id: null }),
    });
    expect(evidenceHref(ref, resolved)).toBeNull();
  });

  it("unresolved evidence has no link", () => {
    const ref: EvidenceRefOut = {
      id: "evt-missing",
      kind: "usage_event",
      measurement: {},
    };
    const unresolved = row({ ref, resolved: false, event: null });
    expect(evidenceHref(ref, unresolved)).toBeNull();
  });
});

describe("ruleLabel", () => {
  it("rule label includes version", () => {
    expect(ruleLabel("retry_amplification", 1)).toBe("retry_amplification.v1");
  });
});

describe("impactLabel", () => {
  it("unknown impact says unknown, never $0", () => {
    expect(impactLabel(null, "USD")).toBe("Potential: unknown");
    expect(impactLabel(null, null)).toBe("Potential: unknown");
    expect(impactLabel(null, "USD")).not.toContain("$0");
    expect(impactLabel(0.22, "USD")).toBe("Potential: $0.22");
  });
});

describe("pollJob", () => {
  it("pollJob resolves on succeeded", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(job({ status: "running" })))
      .mockResolvedValueOnce(
        jsonResponse(job({ status: "succeeded", finished_at: "2026-10-27T10:01:00Z", result: {} })),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await pollJob("job-1", { intervalMs: 1, timeoutMs: 1000 });

    expect(result.status).toBe("succeeded");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("pollJob times out", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(job({ status: "running" })))),
    );

    const pending = pollJob("job-1", { intervalMs: 1000, timeoutMs: 3000 });
    void pending.catch(() => undefined);
    await vi.advanceTimersByTimeAsync(4000);

    const err = await pending.catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ code: "job_timeout", status: 408 });
  });
});

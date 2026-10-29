import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api-types";
import {
  contextSignals,
  eventsTruncated,
  formatTokens,
  outcomeSelectValue,
  reconcilePendingOutcome,
  retryChipLabel,
  shouldCommitFetch,
} from "@/lib/sessions";

type InsightOut = components["schemas"]["InsightOut"];

function insight(partial: Partial<InsightOut> & Pick<InsightOut, "rule_id" | "id">): InsightOut {
  return {
    created_at: "2026-01-01T00:00:00Z",
    detector_type: "rule",
    estimated_impact: null,
    evidence: [],
    evidence_truncated: 0,
    impact_currency: null,
    impact_label: "potential",
    investigator_model: null,
    measurements: {},
    project_id: null,
    recommendation: null,
    root_cause_hypothesis: null,
    rule_version: 1,
    session_id: null,
    severity: "low",
    status: "new",
    summary: "summary",
    task_id: null,
    title: "title",
    ...partial,
  };
}

describe("formatTokens", () => {
  it("formats null tokens as unknown", () => {
    expect(formatTokens(null)).toBe("unknown");
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(1234)).toBe("1,234");
  });
});

describe("retryChipLabel", () => {
  it("retry chip shows attempt and source", () => {
    expect(
      retryChipLabel({
        retry_group_id: "g1",
        attempt: 2,
        retry_source: "inferred",
      }),
    ).toBe("retry · attempt 2 (inferred)");
  });

  it("no chip without a retry group", () => {
    expect(
      retryChipLabel({
        retry_group_id: null,
        attempt: 2,
        retry_source: "inferred",
      }),
    ).toBeNull();
  });
});

describe("eventsTruncated", () => {
  it("detects truncated timeline", () => {
    expect(eventsTruncated(501, 500)).toBe(true);
    expect(eventsTruncated(500, 500)).toBe(false);
    expect(eventsTruncated(10, 10)).toBe(false);
  });
});

describe("contextSignals", () => {
  it("filters repeated-context insights", () => {
    const insights = [
      insight({ id: "1", rule_id: "repeated_context" }),
      insight({ id: "2", rule_id: "retry_amplification" }),
      insight({ id: "3", rule_id: "repeated_context" }),
    ];
    expect(contextSignals(insights).map((i) => i.id)).toEqual(["1", "3"]);
  });
});

describe("shouldCommitFetch", () => {
  it("skips applying results after cancel", () => {
    expect(shouldCommitFetch(true)).toBe(false);
    expect(shouldCommitFetch(false)).toBe(true);
  });
});

describe("outcomeSelectValue / reconcilePendingOutcome", () => {
  it("holds pending selection until server catches up", () => {
    expect(outcomeSelectValue("unknown", "failure")).toBe("failure");
    expect(outcomeSelectValue("failure", null)).toBe("failure");
    expect(reconcilePendingOutcome("unknown", "failure")).toBe("failure");
    expect(reconcilePendingOutcome("failure", "failure")).toBeNull();
  });

  it("rolls pending back to null on error", () => {
    expect(reconcilePendingOutcome("unknown", null)).toBeNull();
  });
});

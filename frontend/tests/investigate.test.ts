import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api-types";
import { latestInvestigation, modeLabel } from "@/lib/investigate";

type InvestigationOut = components["schemas"]["InvestigationOut"];

function investigation(partial: Partial<InvestigationOut> = {}): InvestigationOut {
  return {
    created_at: "2026-10-29T10:00:00.000Z",
    id: "inv-1",
    insight_id: "ins-1",
    mode: "metadata_only",
    model: "muse-spark-1.3-contributor",
    prompt_version: "investigate_v1",
    request_disclosure: null,
    result: null,
    status: "completed",
    validation_errors: null,
    ...partial,
  };
}

describe("modeLabel", () => {
  it("labels metadata_only without excerpts", () => {
    expect(modeLabel("metadata_only")).toBe("metadata only");
  });

  it("labels with_excerpts as including excerpts", () => {
    expect(modeLabel("with_excerpts")).toBe("includes request excerpts");
  });
});

describe("latestInvestigation", () => {
  it("returns null for an empty list", () => {
    expect(latestInvestigation([])).toBeNull();
  });

  it("prefers the newest run by created_at", () => {
    const older = investigation({ id: "old", created_at: "2026-10-28T10:00:00.000Z" });
    const newer = investigation({ id: "new", created_at: "2026-10-29T10:00:00.000Z" });
    expect(latestInvestigation([older, newer])?.id).toBe("new");
    expect(latestInvestigation([newer, older])?.id).toBe("new");
  });
});

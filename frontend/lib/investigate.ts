import type { components } from "@/lib/api-types";

type InvestigationMode = components["schemas"]["InvestigateRequest"]["mode"];
type InvestigationOut = components["schemas"]["InvestigationOut"];

/** Human label for the disclosure dialog: "metadata only" is the default. */
export function modeLabel(mode: InvestigationMode): string {
  return mode === "with_excerpts" ? "includes request excerpts" : "metadata only";
}

/** Newest run first by created_at; ties keep list order. */
export function latestInvestigation(
  investigations: InvestigationOut[],
): InvestigationOut | null {
  if (investigations.length === 0) return null;
  return [...investigations].sort((a, b) =>
    a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0,
  )[0];
}

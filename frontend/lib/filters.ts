export type RangePreset = "24h" | "7d" | "30d" | "custom";
export type OutcomeFilter = "" | "passed" | "failed" | "unknown";

export type OverviewFilters = {
  range: RangePreset;
  /** Anything `new Date()` parses; `datetime-local` values are read as local time. */
  customFrom: string;
  customTo: string;
  projectId: string;
  provider: string;
  modelId: string;
  outcome: OutcomeFilter;
};

export const DEFAULT_FILTERS: OverviewFilters = {
  range: "7d",
  customFrom: "",
  customTo: "",
  projectId: "",
  provider: "",
  modelId: "",
  outcome: "",
};

const HOUR_MS = 60 * 60 * 1000;
const PRESET_MS: Record<Exclude<RangePreset, "custom">, number> = {
  "24h": 24 * HOUR_MS,
  "7d": 7 * 24 * HOUR_MS,
  "30d": 30 * 24 * HOUR_MS,
};
const HOURLY_MAX_MS = 72 * HOUR_MS;

function toIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** Query params for `GET /api/v1/usage/summary`, or null when the custom range is backwards. */
export function summaryParams(filters: OverviewFilters, now: Date): Record<string, string> | null {
  const params: Record<string, string> = {};
  if (filters.range === "custom") {
    const from = toIso(filters.customFrom);
    const to = toIso(filters.customTo);
    if (from && to && from >= to) return null;
    const short = from !== null && to !== null && Date.parse(to) - Date.parse(from) <= HOURLY_MAX_MS;
    if (from) params.from = from;
    if (to) params.to = to;
    params.bucket = short ? "hour" : "day";
  } else {
    params.from = new Date(now.getTime() - PRESET_MS[filters.range]).toISOString();
    params.bucket = filters.range === "24h" ? "hour" : "day";
  }
  if (filters.projectId) params.project_id = filters.projectId;
  if (filters.provider) params.provider = filters.provider;
  if (filters.modelId) params.model_id = filters.modelId;
  if (filters.outcome) params.outcome = filters.outcome;
  return params;
}

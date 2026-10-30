import type { components } from "@/lib/api-types";

type TimeseriesPoint = components["schemas"]["TimeseriesPoint"];
type Bucket = "day" | "hour";

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

export type PadTimeseriesOptions = {
  bucket: Bucket;
  from: string;
  /** Inclusive upper bound when set; defaults to now. */
  to?: string;
};

function alignBucket(iso: string, bucket: Bucket): Date {
  const date = new Date(iso);
  if (bucket === "day") {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  }
  return new Date(
    Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(), date.getUTCHours()),
  );
}

function stepMs(bucket: Bucket): number {
  return bucket === "day" ? DAY_MS : HOUR_MS;
}

/** Fill missing day/hour buckets in `[from, to]` so the chart keeps thin category slots. */
export function padTimeseries(
  points: TimeseriesPoint[],
  options: PadTimeseriesOptions,
): TimeseriesPoint[] {
  if (points.length === 0) return [];

  const currency = points.find((point) => point.currency)?.currency ?? null;
  const byStart = new Map(points.map((point) => [point.bucket_start, point]));

  const start = alignBucket(options.from, options.bucket);
  const end = alignBucket(options.to ?? new Date().toISOString(), options.bucket);
  if (end.getTime() < start.getTime()) {
    return [...points].sort((a, b) => a.bucket_start.localeCompare(b.bucket_start));
  }

  const padded: TimeseriesPoint[] = [];
  for (let cursor = start.getTime(); cursor <= end.getTime(); cursor += stepMs(options.bucket)) {
    const bucket_start = new Date(cursor).toISOString();
    const existing = byStart.get(bucket_start);
    padded.push(
      existing ?? {
        bucket_start,
        estimated_cost: 0,
        currency,
        request_count: 0,
      },
    );
  }
  return padded;
}

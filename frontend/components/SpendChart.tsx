"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { components } from "@/lib/api-types";
import { formatCount, formatMoney } from "@/lib/format";

type TimeseriesPoint = components["schemas"]["TimeseriesPoint"];
type Bucket = "day" | "hour";

type ChartPoint = TimeseriesPoint & { label: string };

function bucketLabel(bucketStart: string, bucket: Bucket): string {
  const date = new Date(bucketStart);
  return bucket === "hour"
    ? date.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        timeZone: "UTC",
      })
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function PointTooltip({ active, payload }: { active?: boolean; payload?: { payload: ChartPoint }[] }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="rounded-md border bg-background px-3 py-2 text-xs shadow-sm">
      <p className="font-medium">{point.label}</p>
      <p>{formatMoney(point.estimated_cost, point.currency)}</p>
      <p className="text-muted-foreground">{formatCount(point.request_count)} requests</p>
    </div>
  );
}

export function SpendChart({
  points,
  bucket,
  currency,
}: {
  points: TimeseriesPoint[];
  bucket: Bucket;
  currency: string | null;
}) {
  if (points.length === 0) {
    return <p className="text-sm text-muted-foreground">No usage in this range.</p>;
  }
  const data: ChartPoint[] = points.map((point) => ({
    ...point,
    label: bucketLabel(point.bucket_start, bucket),
  }));
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} minTickGap={16} />
          <YAxis
            tickLine={false}
            axisLine={false}
            fontSize={12}
            width={72}
            tickFormatter={(value: number) => (currency ? formatMoney(value, currency) : String(value))}
          />
          <Tooltip content={<PointTooltip />} cursor={{ className: "fill-muted" }} />
          <Bar dataKey="estimated_cost" className="fill-primary" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

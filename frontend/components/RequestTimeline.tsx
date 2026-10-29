"use client";

import { CostValue } from "@/components/CostValue";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { components } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/format";
import { formatTokens, retryChipLabel } from "@/lib/sessions";

type UsageEvent = components["schemas"]["UsageEvent"];

const STATUS_VARIANT: Record<
  UsageEvent["status"],
  "default" | "secondary" | "outline" | "destructive"
> = {
  success: "secondary",
  error: "destructive",
  timeout: "destructive",
  unknown: "outline",
};

type RequestTimelineProps = {
  events: UsageEvent[];
  requestCount: number;
  truncated: boolean;
};

export function RequestTimeline({ events, requestCount, truncated }: RequestTimelineProps) {
  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">No requests in this session.</p>;
  }

  return (
    <div className="space-y-3">
      {truncated ? (
        <p className="text-sm text-muted-foreground">
          Showing first 500 of {requestCount}
        </p>
      ) : null}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Tokens in</TableHead>
            <TableHead className="text-right">Tokens out</TableHead>
            <TableHead className="text-right">Cost</TableHead>
            <TableHead>Retry</TableHead>
            <TableHead>Error</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {events.map((event) => {
            const chip = retryChipLabel(event);
            const cost = event.cost?.estimated_cost ?? null;
            const currency = event.cost?.currency ?? null;
            return (
              <TableRow key={event.id} id={`event-${event.id}`}>
                <TableCell className="tabular-nums text-muted-foreground">
                  {formatTimestamp(event.started_at)}
                </TableCell>
                <TableCell className="max-w-40 truncate font-mono text-xs" title={event.model_id}>
                  {event.model_id}
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[event.status]}>{event.status}</Badge>
                </TableCell>
                <TableCell className="text-right font-mono text-xs tabular-nums">
                  {formatTokens(event.input_tokens)}
                </TableCell>
                <TableCell className="text-right font-mono text-xs tabular-nums">
                  {formatTokens(event.output_tokens)}
                </TableCell>
                <TableCell className="text-right">
                  <CostValue value={cost} currency={currency} />
                </TableCell>
                <TableCell>
                  {chip ? (
                    <Badge variant="outline" className="font-normal">
                      {chip}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="max-w-32 truncate text-muted-foreground" title={event.error_category ?? undefined}>
                  {event.error_category ?? "—"}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

"use client";

import Link from "next/link";

import { CostValue } from "@/components/CostValue";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { components } from "@/lib/api-types";
import { evidenceHref } from "@/lib/insights";
import { formatTokens } from "@/lib/sessions";

type ResolvedEvidence = components["schemas"]["ResolvedEvidence"];

function measurementText(measurement: Record<string, unknown>): string {
  const entries = Object.entries(measurement);
  if (entries.length === 0) return "—";
  return entries
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(", ");
}

type EvidenceTableProps = {
  rows: ResolvedEvidence[];
  truncated: number;
};

export function EvidenceTable({ rows, truncated }: EvidenceTableProps) {
  if (rows.length === 0) {
    return (
      <div data-testid="evidence-table" className="space-y-2">
        <p className="text-sm text-muted-foreground">No evidence rows.</p>
        {truncated > 0 ? (
          <p className="text-sm text-muted-foreground">+{truncated} more not shown</p>
        ) : null}
      </div>
    );
  }

  return (
    <div data-testid="evidence-table" className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Kind</TableHead>
            <TableHead>Id</TableHead>
            <TableHead>Measurement</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Tokens</TableHead>
            <TableHead className="text-right">Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const href = evidenceHref(row.ref, row);
            const event = row.event;
            const idCell = href ? (
              <Link
                href={href}
                className="font-mono text-xs underline-offset-4 hover:underline"
                title={row.ref.id}
              >
                {row.ref.id}
              </Link>
            ) : (
              <span className="font-mono text-xs" title={row.ref.id}>
                {row.resolved ? row.ref.id : "evidence missing"}
              </span>
            );
            const tokens =
              event == null
                ? "—"
                : `${formatTokens(event.input_tokens)} / ${formatTokens(event.output_tokens)}`;
            return (
              <TableRow key={`${row.ref.kind}-${row.ref.id}`}>
                <TableCell className="whitespace-nowrap">{row.ref.kind}</TableCell>
                <TableCell className="max-w-48 truncate">{idCell}</TableCell>
                <TableCell
                  className="max-w-56 truncate font-mono text-xs text-muted-foreground"
                  title={measurementText(row.ref.measurement)}
                >
                  {row.resolved ? measurementText(row.ref.measurement) : "evidence missing"}
                </TableCell>
                <TableCell className="max-w-40 truncate font-mono text-xs" title={event?.model_id}>
                  {event?.model_id ?? "—"}
                </TableCell>
                <TableCell>{event?.status ?? "—"}</TableCell>
                <TableCell className="text-right font-mono text-xs tabular-nums">{tokens}</TableCell>
                <TableCell className="text-right">
                  {event ? (
                    <CostValue
                      value={event.cost?.estimated_cost ?? null}
                      currency={event.cost?.currency ?? null}
                    />
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {truncated > 0 ? (
        <p className="text-sm text-muted-foreground">+{truncated} more not shown</p>
      ) : null}
    </div>
  );
}

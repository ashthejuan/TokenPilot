"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type MeasurementsTableProps = {
  measurements: Record<string, unknown>;
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function MeasurementsTable({ measurements }: MeasurementsTableProps) {
  const entries = Object.entries(measurements);
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No measurements.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Key</TableHead>
          <TableHead>Value</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map(([key, value]) => (
          <TableRow key={key}>
            <TableCell className="max-w-48 truncate font-mono text-xs" title={key}>
              {key}
            </TableCell>
            <TableCell
              className="max-w-md truncate font-mono text-xs tabular-nums"
              title={formatValue(value)}
            >
              {formatValue(value)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

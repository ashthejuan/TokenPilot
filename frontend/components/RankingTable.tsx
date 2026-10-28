import type { ReactNode } from "react";

import { CostValue } from "@/components/CostValue";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCount } from "@/lib/format";

export type RankingRow = {
  key: string;
  label: ReactNode;
  detail?: ReactNode;
  requests: number;
  cost: number | null;
  currency: string | null;
};

type RankingTableProps = {
  rows: RankingRow[];
  nameHeader: string;
  detailHeader?: string;
  emptyText: string;
};

export function RankingTable({ rows, nameHeader, detailHeader, emptyText }: RankingTableProps) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyText}</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{nameHeader}</TableHead>
          {detailHeader ? <TableHead>{detailHeader}</TableHead> : null}
          <TableHead className="text-right">Requests</TableHead>
          <TableHead className="text-right">Cost</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.key}>
            <TableCell className="max-w-64 truncate font-medium">{row.label}</TableCell>
            {detailHeader ? <TableCell>{row.detail}</TableCell> : null}
            <TableCell className="text-right tabular-nums">{formatCount(row.requests)}</TableCell>
            <TableCell className="text-right">
              <CostValue value={row.cost} currency={row.currency} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

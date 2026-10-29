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
import {
  formatDurationMs,
  patchHref,
  type BenchmarkRunOut,
} from "@/lib/benchmarks";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

const STATUS_CLASS: Record<BenchmarkRunOut["run_status"], string> = {
  queued: "border-border bg-muted text-muted-foreground",
  running: "border-transparent bg-blue-500/15 text-blue-800 dark:text-blue-200",
  completed: "border-transparent bg-secondary text-secondary-foreground",
  failed: "border-transparent bg-destructive/10 text-destructive",
};

const STATUS_LABEL: Record<BenchmarkRunOut["run_status"], string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
};

/** Per-row stagger step for the first-load entrance; see globals.css. */
const STAGGER_MS = 50;
const STAGGER_CAP = 8;

export function RunTable({ runs, stagger }: { runs: BenchmarkRunOut[]; stagger: boolean }) {
  if (runs.length === 0) {
    return <p className="text-sm text-muted-foreground">No runs yet.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Variant</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Outcome</TableHead>
          <TableHead>Cost</TableHead>
          <TableHead>Tokens</TableHead>
          <TableHead>Runtime</TableHead>
          <TableHead>Requests</TableHead>
          <TableHead>Retries</TableHead>
          <TableHead>Tests</TableHead>
          <TableHead>Patch</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run, index) => (
          <TableRow
            key={run.id}
            className={cn(stagger && "benchmark-row-enter")}
            style={stagger ? { animationDelay: `${Math.min(index, STAGGER_CAP) * STAGGER_MS}ms` } : undefined}
          >
            <TableCell className="font-medium">{run.variant_name}</TableCell>
            <TableCell>
              <Badge variant="outline" className={cn(STATUS_CLASS[run.run_status])}>
                {STATUS_LABEL[run.run_status]}
              </Badge>
            </TableCell>
            <TableCell>{run.outcome ?? "—"}</TableCell>
            <TableCell className="tabular-nums">
              <CostValue value={run.total_cost} currency={run.currency} />
            </TableCell>
            <TableCell className="tabular-nums">{formatCount(run.total_tokens)}</TableCell>
            <TableCell className="tabular-nums">{formatDurationMs(run.duration_ms)}</TableCell>
            <TableCell className="tabular-nums">{run.request_count}</TableCell>
            <TableCell className="tabular-nums">{run.retry_count}</TableCell>
            <TableCell className="tabular-nums">
              {run.test_exit_code === null ? "—" : `exit ${run.test_exit_code}`}
            </TableCell>
            <TableCell>
              {run.patch_path ? (
                <a
                  href={patchHref(run.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="underline-offset-4 hover:underline"
                >
                  Patch
                </a>
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

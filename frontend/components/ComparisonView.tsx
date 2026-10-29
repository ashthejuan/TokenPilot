import { CostValue } from "@/components/CostValue";
import { SavingsBadge } from "@/components/SavingsBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  eligibleRuns,
  formatDurationMs,
  methodologyFlag,
  methodologyNumber,
  methodologyStrings,
  patchHref,
  sumNullable,
  variablesChangedLabel,
  type BenchmarkRunOut,
  type ComparisonOut,
} from "@/lib/benchmarks";
import { addMoney, formatCount, formatMoney, formatPct } from "@/lib/format";

function configText(config: Record<string, unknown>, key: string): string {
  const value: unknown = config[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "—";
}

function firstCurrency(runs: BenchmarkRunOut[]): string | null {
  for (const run of runs) {
    if (run.currency !== null) return run.currency;
  }
  return null;
}

function outcomesSummary(runs: BenchmarkRunOut[]): string {
  const counts = new Map<string, number>();
  for (const run of runs) {
    if (run.outcome !== null) counts.set(run.outcome, (counts.get(run.outcome) ?? 0) + 1);
  }
  if (counts.size === 0) return "No scored runs";
  return [...counts]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([outcome, count]) => (count > 1 ? `${count} ${outcome}` : outcome))
    .join(", ");
}

function deltaLine(comparison: ComparisonOut, currency: string | null): string {
  const delta = comparison.cost_delta;
  if (delta === null) return "Savings unknown";
  const pctRaw = comparison.cost_delta_pct === null ? null : Number(comparison.cost_delta_pct);
  const pct = pctRaw === null || Number.isNaN(pctRaw) ? null : `${pctRaw.toFixed(1)}%`;
  const amount = formatMoney(Math.abs(delta), currency);
  if (delta > 0) return pct ? `Saves ${amount} (${pct})` : `Saves ${amount}`;
  if (delta < 0) return pct ? `Costs ${amount} more (${pct} more)` : `Costs ${amount} more`;
  return "No cost difference";
}

function PatchLinks({ runs }: { runs: BenchmarkRunOut[] }) {
  const withPatch = runs.filter((run) => run.patch_path !== null);
  if (withPatch.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1">
      {withPatch.map((run) => (
        <a
          key={run.id}
          href={patchHref(run.id)}
          target="_blank"
          rel="noreferrer"
          className="underline-offset-4 hover:underline"
        >
          {run.repeat_index === null ? "Patch" : `Patch (run ${run.repeat_index + 1})`}
        </a>
      ))}
    </span>
  );
}

export function ComparisonView({
  comparison,
  runs,
}: {
  comparison: ComparisonOut;
  runs: BenchmarkRunOut[];
}) {
  const baselineRuns = runs.filter((run) => run.variant_name === comparison.baseline_variant);
  const alternativeRuns = runs.filter(
    (run) => run.variant_name === comparison.alternative_variant,
  );
  const sides = [
    { label: comparison.baseline_variant, runs: baselineRuns },
    { label: comparison.alternative_variant, runs: alternativeRuns },
  ].map((side) => ({ ...side, eligible: eligibleRuns(side.runs) }));
  const currency = firstCurrency(baselineRuns) ?? firstCurrency(alternativeRuns);
  const methodology = comparison.methodology;
  const lowSample = methodologyFlag(methodology, "low_sample");
  const interleaved = methodologyFlag(methodology, "interleaved");
  const reasons = comparison.reasons ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <SavingsBadge
          status={comparison.comparison_status}
          correctness_preserved={comparison.correctness_preserved}
          cost_delta={comparison.cost_delta}
          reasons={reasons}
        />
        <p className="text-sm font-medium tabular-nums">{deltaLine(comparison, currency)}</p>
      </div>
      <p className="text-sm text-muted-foreground">
        {variablesChangedLabel(methodologyStrings(methodology, "variables_changed"))}
      </p>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Metric</TableHead>
            <TableHead>{comparison.baseline_variant}</TableHead>
            <TableHead>{comparison.alternative_variant}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell className="font-medium">Model</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label}>
                {side.runs[0]?.model_id ?? configText(side.runs[0]?.config ?? {}, "model_id")}
              </TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Context strategy</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label}>
                {configText(side.runs[0]?.config ?? {}, "context_strategy")}
              </TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Max steps</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label} className="tabular-nums">
                {configText(side.runs[0]?.config ?? {}, "max_steps")}
              </TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Total (eligible runs)</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label} className="tabular-nums">
                <CostValue
                  value={addMoney(...side.eligible.map((run) => run.total_cost))}
                  currency={firstCurrency(side.eligible)}
                />
              </TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Tokens</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label} className="tabular-nums">
                {formatCount(sumNullable(...side.eligible.map((run) => run.total_tokens)))}
              </TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Runtime</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label} className="tabular-nums">
                {formatDurationMs(sumNullable(...side.eligible.map((run) => run.duration_ms)))}
              </TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Requests</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label} className="tabular-nums">
                {side.eligible.reduce((sum, run) => sum + run.request_count, 0)}
              </TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Retries</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label} className="tabular-nums">
                {side.eligible.reduce((sum, run) => sum + run.retry_count, 0)}
              </TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Outcomes</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label}>{outcomesSummary(side.runs)}</TableCell>
            ))}
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Patches</TableCell>
            {sides.map((side) => (
              <TableCell key={side.label}>
                <PatchLinks runs={side.runs} />
              </TableCell>
            ))}
          </TableRow>
        </TableBody>
      </Table>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">Methodology</h3>
        <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Repeats (baseline / alternative)</dt>
            <dd className="tabular-nums">
              {methodologyNumber(methodology, "repeat_counts", "baseline") ?? "—"}
              {" / "}
              {methodologyNumber(methodology, "repeat_counts", "alternative") ?? "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Eligible (baseline / alternative)</dt>
            <dd className="tabular-nums">
              {methodologyNumber(methodology, "eligible_counts", "baseline") ?? "—"}
              {" / "}
              {methodologyNumber(methodology, "eligible_counts", "alternative") ?? "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Success rate (baseline / alternative)</dt>
            <dd className="tabular-nums">
              {formatPct(
                (() => {
                  const rate = methodologyNumber(methodology, "success_rates", "baseline");
                  return rate === null ? null : rate * 100;
                })(),
              )}
              {" / "}
              {formatPct(
                (() => {
                  const rate = methodologyNumber(methodology, "success_rates", "alternative");
                  return rate === null ? null : rate * 100;
                })(),
              )}
            </dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Cost stdev (baseline / alternative)</dt>
            <dd className="tabular-nums">
              {formatMoney(
                methodologyNumber(methodology, "cost_stdev", "baseline"),
                currency,
              )}
              {" / "}
              {formatMoney(
                methodologyNumber(methodology, "cost_stdev", "alternative"),
                currency,
              )}
            </dd>
          </div>
        </dl>
        {lowSample ? (
          <p role="note" className="text-sm text-amber-800 dark:text-amber-200">
            Low sample: fewer than 3 eligible runs per variant. Treat the classification as
            preliminary.
          </p>
        ) : null}
        {interleaved ? (
          <p className="text-sm text-muted-foreground">
            Runs were interleaved across variants to spread time-based noise.
          </p>
        ) : null}
        {reasons.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

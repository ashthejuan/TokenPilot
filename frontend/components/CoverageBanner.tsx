import type { components } from "@/lib/api-types";
import { formatCount, formatPct } from "@/lib/format";

type Coverage = components["schemas"]["Coverage"];

export function CoverageBanner({
  coverage,
  eventsWithUnknownCost,
}: {
  coverage: Coverage;
  eventsWithUnknownCost: number;
}) {
  const partlyPriced = coverage.priced_pct !== null && coverage.priced_pct < 100;
  const mixed = coverage.mixed_currency === true;
  if (!partlyPriced && eventsWithUnknownCost === 0 && !mixed) return null;

  return (
    <div
      role="status"
      className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100"
    >
      <p className="font-medium">Some spend is not counted in these totals.</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {eventsWithUnknownCost > 0 ? (
          <li>
            {formatCount(eventsWithUnknownCost)} event{eventsWithUnknownCost === 1 ? " has" : "s have"} no
            cost because pricing or usage data is missing.
          </li>
        ) : null}
        {partlyPriced ? <li>Priced coverage: {formatPct(coverage.priced_pct)} of events.</li> : null}
        {mixed ? (
          <li>Costs are in more than one currency, so they are not added into one total.</li>
        ) : null}
      </ul>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { BasisBadge } from "@/components/BasisBadge";
import { CostValue } from "@/components/CostValue";
import { CoverageBanner } from "@/components/CoverageBanner";
import { Filters } from "@/components/Filters";
import { RankingTable, type RankingRow } from "@/components/RankingTable";
import { SavingsBadge } from "@/components/SavingsBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { SpendChart } from "@/components/SpendChart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiGet } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { latestComparison, type BenchmarkOut, type ComparisonOut } from "@/lib/benchmarks";
import { DEFAULT_FILTERS, summaryParams } from "@/lib/filters";
import { addMoney, formatCount, moneyOrZero } from "@/lib/format";
import { impactLabel, ruleLabel } from "@/lib/insights";

type UsageSummary = components["schemas"]["UsageSummary"];
type Project = components["schemas"]["Project"];
type InsightOut = components["schemas"]["InsightOut"];
type PagedInsights = components["schemas"]["Paged_InsightOut_"];
type Bucket = "day" | "hour";
type LatestBenchmark = { benchmark: BenchmarkOut; latest: ComparisonOut | null };

// A summary holds the backend's single DB lock (~0.7 s at 100k events), so fetch on change only.
const FETCH_DEBOUNCE_MS = 300;

const OUTCOME_LABEL: Record<string, string> = {
  success: "Success",
  failure: "Failure",
  abandoned: "Abandoned",
  unknown: "Unknown",
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "proxy_not_configured") {
      return "The web server has no local token. Start it with `make dev-web`.";
    }
    if (error.code === "upstream_unreachable" || error.code === "upstream_timeout") {
      return "The TokenPilot API is not answering. Start it with `make dev-api`.";
    }
    return `${error.message} (${error.code})`;
  }
  return "Could not reach the TokenPilot web server.";
}

function mergeSorted(current: string[], incoming: string[]): string[] {
  const merged = new Set([...current, ...incoming]);
  return merged.size === current.length ? current : [...merged].sort();
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium tabular-nums">{children}</p>
    </div>
  );
}

export default function OverviewPage() {
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [bucket, setBucket] = useState<Bucket>("day");
  const [projects, setProjects] = useState<Project[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recentInsights, setRecentInsights] = useState<InsightOut[]>([]);
  const [insightsLoading, setInsightsLoading] = useState(true);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [latestBenchmarks, setLatestBenchmarks] = useState<LatestBenchmark[]>([]);
  const [benchmarksLoading, setBenchmarksLoading] = useState(true);
  const [benchmarksError, setBenchmarksError] = useState<string | null>(null);

  const rangeError =
    filters.range === "custom" && summaryParams(filters, new Date()) === null
      ? "The start must be before the end."
      : null;

  useEffect(() => {
    let cancelled = false;
    apiGet<Project[]>("api/v1/projects")
      .then((list) => {
        if (!cancelled) setProjects(list);
      })
      .catch(() => {
        // The summary request reports connection problems; the filter just lists no projects.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setInsightsLoading(true);
    apiGet<PagedInsights>("api/v1/insights", { status: "new", limit: "5" })
      .then((page) => {
        if (cancelled) return;
        setRecentInsights(page.items);
        setInsightsError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setInsightsError(errorText(err));
      })
      .finally(() => {
        if (!cancelled) setInsightsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  useEffect(() => {
    let cancelled = false;
    setBenchmarksLoading(true);
    apiGet<BenchmarkOut[]>("api/v1/benchmarks")
      .then(async (benchmarks) => {
        const recent = [...benchmarks].reverse().slice(0, 5);
        const rows = await Promise.all(
          recent.map(async (benchmark) => {
            const comparisons = await apiGet<ComparisonOut[]>(
              `api/v1/benchmarks/${benchmark.id}/comparisons`,
            );
            return { benchmark, latest: latestComparison(comparisons) };
          }),
        );
        if (cancelled) return;
        setLatestBenchmarks(rows);
        setBenchmarksError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setBenchmarksError(errorText(err));
      })
      .finally(() => {
        if (!cancelled) setBenchmarksLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  useEffect(() => {
    const params = summaryParams(filters, new Date());
    if (params === null) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      apiGet<UsageSummary>("api/v1/usage/summary", params)
        .then((next) => {
          if (cancelled) return;
          setSummary(next);
          setBucket(params.bucket as Bucket);
          setError(null);
          setProviders((current) => mergeSorted(current, next.by_model.map((m) => m.provider)));
          setModels((current) => mergeSorted(current, next.by_model.map((m) => m.model_id)));
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(errorText(err));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [filters, refreshKey]);

  const projectNames = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects],
  );

  const projectRows: RankingRow[] = (summary?.by_project ?? []).map((row) => ({
    key: row.project_id ?? "unattributed",
    label: row.project_id === null ? <span className="italic">Unattributed</span> : row.name,
    requests: row.request_count,
    cost: row.estimated_cost,
    currency: row.currency,
  }));

  const sessionRows: RankingRow[] = (summary?.top_sessions ?? []).map((row) => ({
    key: row.session_id,
    label: (
      <span title={row.session_id}>
        <span className="font-mono text-xs">{row.session_id.slice(0, 8)}</span>{" "}
        <span className="text-muted-foreground">
          {row.project_id === null ? "Unattributed" : (projectNames.get(row.project_id) ?? row.project_id)}
        </span>
      </span>
    ),
    detail: OUTCOME_LABEL[row.outcome] ?? row.outcome,
    requests: row.request_count,
    cost: row.estimated_cost,
    currency: row.currency,
  }));

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Overview</h1>
        <Button variant="outline" size="sm" onClick={() => setRefreshKey((key) => key + 1)} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </Button>
      </div>

      <Filters
        value={filters}
        onChange={setFilters}
        projects={projects}
        providers={providers}
        models={models}
        rangeError={rangeError}
      />

      {error ? (
        <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {summary === null ? (
        !error ? <p className="text-sm text-muted-foreground">Loading usage…</p> : null
      ) : (
        <div className={loading ? "space-y-6 opacity-60 transition-opacity" : "space-y-6"}>
          <Section title="Recorded spend">
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <CostValue
                  value={summary.total_estimated_cost}
                  currency={summary.currency}
                  className="text-3xl font-semibold"
                />
                <BasisBadge basis={summary.cost_basis} />
              </div>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Requests">{formatCount(summary.request_count)}</Stat>
                <Stat label="Failed requests">{formatCount(summary.failed_count)}</Stat>
                <Stat label="Input tokens">{formatCount(summary.input_tokens)}</Stat>
                <Stat label="Output tokens">{formatCount(summary.output_tokens)}</Stat>
                {summary.total_reported_cost !== null ? (
                  <Stat label="Reported by provider">
                    <CostValue value={summary.total_reported_cost} currency={summary.currency} />
                  </Stat>
                ) : null}
              </div>
              {summary.events_with_unknown_tokens > 0 ? (
                <p className="text-xs text-muted-foreground">
                  Token totals exclude {formatCount(summary.events_with_unknown_tokens)} events that did
                  not report usage.
                </p>
              ) : null}
              <CoverageBanner
                coverage={summary.coverage}
                eventsWithUnknownCost={summary.events_with_unknown_cost}
              />
            </div>
          </Section>

          <Section
            title="Spend over time"
            description={bucket === "day" ? "Estimated cost per UTC day" : "Estimated cost per hour"}
          >
            <SpendChart points={summary.timeseries} bucket={bucket} currency={summary.currency} />
          </Section>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Most expensive projects">
              <RankingTable
                rows={projectRows}
                nameHeader="Project"
                emptyText="No project usage in this range."
              />
            </Section>
            <Section title="Highest-cost sessions">
              <RankingTable
                rows={sessionRows}
                nameHeader="Session"
                detailHeader="Outcome"
                emptyText="No sessions in this range."
              />
            </Section>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section
              title="Failed and unverified work"
              description="Spend on tasks or sessions that failed or have no recorded outcome"
            >
              <div className="space-y-3">
                <CostValue
                  value={moneyOrZero(
                    addMoney(summary.cost_by_outcome.failed, summary.cost_by_outcome.unknown),
                    summary.currency,
                    summary.events_with_unknown_cost,
                  )}
                  currency={summary.currency}
                  className="text-2xl font-semibold"
                />
                <div className="grid grid-cols-2 gap-4">
                  <Stat label="Failed">
                    <CostValue
                      value={moneyOrZero(
                        summary.cost_by_outcome.failed,
                        summary.currency,
                        summary.events_with_unknown_cost,
                      )}
                      currency={summary.currency}
                    />
                  </Stat>
                  <Stat label="Unverified">
                    <CostValue
                      value={moneyOrZero(
                        summary.cost_by_outcome.unknown,
                        summary.currency,
                        summary.events_with_unknown_cost,
                      )}
                      currency={summary.currency}
                    />
                  </Stat>
                </div>
              </div>
            </Section>
            <Section title="Retry spend" description="Spend on second and later attempts">
              <div className="space-y-3">
                <CostValue
                  value={moneyOrZero(
                    summary.retry_cost,
                    summary.currency,
                    summary.events_with_unknown_cost,
                  )}
                  currency={summary.currency}
                  className="text-2xl font-semibold"
                />
                <Stat label="Retried requests">{formatCount(summary.retry_count)}</Stat>
              </div>
            </Section>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Recent insights">
              {insightsLoading ? (
                <p className="text-sm text-muted-foreground">Loading insights…</p>
              ) : insightsError ? (
                <p className="text-sm text-destructive">{insightsError}</p>
              ) : recentInsights.length === 0 ? (
                <p className="text-sm text-muted-foreground">No new insights yet.</p>
              ) : (
                <ul className="space-y-3">
                  {recentInsights.map((insight) => (
                    <li key={insight.id} className="flex flex-wrap items-start gap-2">
                      <SeverityBadge severity={insight.severity} />
                      <div className="min-w-0 flex-1">
                        <Link
                          href={`/insights/${insight.id}`}
                          className="block truncate text-sm font-medium underline-offset-4 hover:underline"
                          title={insight.title}
                        >
                          {insight.title}
                        </Link>
                        <p className="truncate text-xs text-muted-foreground">
                          <span className="font-mono">
                            {ruleLabel(insight.rule_id, insight.rule_version)}
                          </span>
                          {" · "}
                          {impactLabel(insight.estimated_impact, insight.impact_currency)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
            <Section title="Latest benchmarks">
              {benchmarksLoading ? (
                <p className="text-sm text-muted-foreground">Loading benchmarks…</p>
              ) : benchmarksError ? (
                <p className="text-sm text-destructive">{benchmarksError}</p>
              ) : latestBenchmarks.length === 0 ? (
                <p className="text-sm text-muted-foreground">No benchmarks yet.</p>
              ) : (
                <ul className="space-y-3">
                  {latestBenchmarks.map(({ benchmark, latest }) => (
                    <li key={benchmark.id} className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/benchmarks/${benchmark.id}`}
                        className="min-w-0 flex-1 truncate text-sm font-medium underline-offset-4 hover:underline"
                        title={benchmark.name}
                      >
                        {benchmark.name}
                      </Link>
                      {latest !== null ? (
                        <SavingsBadge
                          status={latest.comparison_status}
                          correctness_preserved={latest.correctness_preserved}
                          cost_delta={latest.cost_delta}
                          reasons={latest.reasons ?? []}
                        />
                      ) : (
                        <SavingsBadge
                          status="potential"
                          correctness_preserved={null}
                          cost_delta={null}
                        />
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}

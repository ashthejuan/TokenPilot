"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ComparisonView } from "@/components/ComparisonView";
import { RunTable } from "@/components/RunTable";
import { SavingsBadge } from "@/components/SavingsBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiGet, apiSend } from "@/lib/api";
import {
  isRunActive,
  latestComparison,
  methodologyStrings,
  variablesChangedLabel,
  type BenchmarkDetail,
  type ComparisonOut,
} from "@/lib/benchmarks";

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

const POLL_INTERVAL_MS = 2000;

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "proxy_not_configured") {
      return "The web server has no local token. Start it with `make dev-web`.";
    }
    if (error.code === "upstream_unreachable" || error.code === "upstream_timeout") {
      return "The TokenPilot API is not answering. Start it with `make dev-api`.";
    }
    if (error.status === 404) return "Benchmark not found.";
    return `${error.message} (${error.code})`;
  }
  return "Could not reach the TokenPilot web server.";
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

/** Declared alternative changes, until a comparison reports measured variables. */
function declaredChanges(detail: BenchmarkDetail): string[] {
  const keys = new Set<string>();
  for (const spec of detail.alternatives) {
    for (const key of Object.keys(spec.changes ?? {})) keys.add(key);
  }
  return [...keys].sort();
}

export default function BenchmarkDetailPage() {
  const params = useParams<{ id: string }>();
  const benchmarkId = params.id;

  const [detail, setDetail] = useState<BenchmarkDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [comparison, setComparison] = useState<ComparisonOut | null>(null);
  const [baselineVariant, setBaselineVariant] = useState("baseline");
  const [alternativeVariant, setAlternativeVariant] = useState("");
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  const fetchDetail = useCallback(
    () => apiGet<BenchmarkDetail>(`api/v1/benchmarks/${benchmarkId}`),
    [benchmarkId],
  );

  const fetchComparisons = useCallback(
    () => apiGet<ComparisonOut[]>(`api/v1/benchmarks/${benchmarkId}/comparisons`),
    [benchmarkId],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchDetail()
      .then((next) => {
        if (cancelled) return;
        setDetail(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    // Independent fetch: a comparisons failure degrades to the potential
    // badge and never blanks the detail page.
    fetchComparisons()
      .then((comparisons) => {
        if (!cancelled) setComparison(latestComparison(comparisons));
      })
      .catch(() => {
        if (!cancelled) setComparison(null);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchDetail, fetchComparisons]);

  const hasActive = useMemo(
    () => (detail?.runs ?? []).some(isRunActive),
    [detail],
  );

  useEffect(() => {
    if (!hasActive) return;
    let cancelled = false;
    const timer = setInterval(() => {
      fetchDetail()
        .then((next) => {
          if (!cancelled) setDetail(next);
        })
        .catch(() => {
          // Keep the last good state; the next tick retries.
        });
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [hasActive, fetchDetail]);

  // First-load entrance only: poll refreshes update text instantly.
  const staggerRef = useRef(true);
  useEffect(() => {
    if (detail !== null) staggerRef.current = false;
  }, [detail]);

  useEffect(() => {
    if (detail && alternativeVariant === "") {
      setAlternativeVariant(detail.alternatives[0]?.name ?? "");
    }
  }, [detail, alternativeVariant]);

  async function runCompare() {
    if (comparing) return;
    if (baselineVariant === alternativeVariant) {
      setCompareError("Baseline and alternative must differ.");
      return;
    }
    setComparing(true);
    setCompareError(null);
    try {
      await apiSend<ComparisonOut>(
        "POST",
        `api/v1/benchmarks/${benchmarkId}/compare`,
        { baseline_variant: baselineVariant, alternative_variant: alternativeVariant },
      );
      setDetail(await fetchDetail());
      setComparison(latestComparison(await fetchComparisons()));
    } catch (err: unknown) {
      setCompareError(errorText(err));
    } finally {
      setComparing(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl">
        <p className="text-sm text-muted-foreground">Loading benchmark…</p>
      </div>
    );
  }

  if (error || detail === null) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Link href="/benchmarks" className="text-sm text-muted-foreground underline-offset-4 hover:underline">
          ← Benchmarks
        </Link>
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error ?? "Benchmark not found."}
        </div>
      </div>
    );
  }

  const runs = detail.runs ?? [];
  const variants = ["baseline", ...detail.alternatives.map((spec) => spec.name)];
  const diffLabel =
    comparison !== null
      ? variablesChangedLabel(methodologyStrings(comparison.methodology, "variables_changed"))
      : variablesChangedLabel(declaredChanges(detail));

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="space-y-3">
        <Link href="/benchmarks" className="text-sm text-muted-foreground underline-offset-4 hover:underline">
          ← Benchmarks
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{detail.name}</h1>
          {comparison !== null ? (
            <SavingsBadge
              status={comparison.comparison_status}
              correctness_preserved={comparison.correctness_preserved}
              cost_delta={comparison.cost_delta}
              reasons={comparison.reasons ?? []}
            />
          ) : (
            <SavingsBadge status="potential" correctness_preserved={null} cost_delta={null} />
          )}
        </div>
        {detail.description ? (
          <p className="text-sm text-muted-foreground">{detail.description}</p>
        ) : null}
        <p className="text-sm text-muted-foreground">{diffLabel}</p>
      </div>

      <Section title="Runs" description="Status refreshes every 2 seconds while runs are active.">
        <RunTable runs={runs} stagger={staggerRef.current} />
      </Section>

      <Section title="Compare variants">
        {compareError ? (
          <p role="alert" className="mb-3 text-sm text-destructive">
            {compareError}
          </p>
        ) : null}
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Baseline
            <select
              className={SELECT_CLASS}
              value={baselineVariant}
              onChange={(e) => setBaselineVariant(e.target.value)}
            >
              {variants.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Alternative
            <select
              className={SELECT_CLASS}
              value={alternativeVariant}
              onChange={(e) => setAlternativeVariant(e.target.value)}
            >
              {variants.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <Button
            className="pressable"
            size="sm"
            onClick={() => void runCompare()}
            disabled={comparing || variants.length < 2}
          >
            {comparing ? "Comparing…" : "Compare"}
          </Button>
        </div>
      </Section>

      {comparison !== null ? (
        <Section title="Comparison">
          <ComparisonView comparison={comparison} runs={runs} />
        </Section>
      ) : null}
    </div>
  );
}

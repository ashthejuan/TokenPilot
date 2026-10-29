"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { NewBenchmarkForm } from "@/components/NewBenchmarkForm";
import { SavingsBadge } from "@/components/SavingsBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiGet } from "@/lib/api";
import {
  benchmarkStatus,
  latestComparison,
  type BenchmarkDetail,
  type BenchmarkOut,
  type BenchmarkStatus,
  type ComparisonOut,
} from "@/lib/benchmarks";
import { formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

const STATUS_BADGE: Record<BenchmarkStatus, { label: string; className: string }> = {
  empty: { label: "No runs yet", className: "border-border bg-muted text-muted-foreground" },
  running: {
    label: "Running",
    className: "border-transparent bg-blue-500/15 text-blue-800 dark:text-blue-200",
  },
  done: { label: "Completed", className: "border-transparent bg-secondary text-secondary-foreground" },
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

export default function BenchmarksPage() {
  const router = useRouter();
  const [rows, setRows] = useState<
    { benchmark: BenchmarkOut; runs: number; status: BenchmarkStatus; latest: ComparisonOut | null }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiGet<BenchmarkOut[]>("api/v1/benchmarks")
      .then(async (benchmarks) => {
        const details = await Promise.all(
          benchmarks.map(async (benchmark) => {
            const [detail, comparisons] = await Promise.all([
              apiGet<BenchmarkDetail>(`api/v1/benchmarks/${benchmark.id}`),
              apiGet<ComparisonOut[]>(`api/v1/benchmarks/${benchmark.id}/comparisons`),
            ]);
            return { detail, comparisons };
          }),
        );
        if (cancelled) return;
        setRows(
          details.map(({ detail, comparisons }) => {
            const runs = detail.runs ?? [];
            return {
              benchmark: detail,
              runs: runs.length,
              status: benchmarkStatus(runs),
              latest: latestComparison(comparisons),
            };
          }),
        );
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-2xl font-semibold">Benchmarks</h1>
        <Button
          className="pressable"
          size="sm"
          variant={showForm ? "secondary" : "default"}
          onClick={() => setShowForm((open) => !open)}
        >
          {showForm ? "Close" : "New benchmark"}
        </Button>
      </div>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}

      {showForm ? (
        <Card>
          <CardHeader>
            <CardTitle>New benchmark</CardTitle>
          </CardHeader>
          <CardContent>
            <NewBenchmarkForm onCreated={(id) => router.push(`/benchmarks/${id}`)} />
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Benchmarks</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading benchmarks…</p>
          ) : rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">No benchmarks yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Runs</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Savings</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map(({ benchmark, runs, status, latest }) => {
                  const badge = STATUS_BADGE[status];
                  return (
                    <TableRow key={benchmark.id}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/benchmarks/${benchmark.id}`}
                          className="underline-offset-4 hover:underline"
                        >
                          {benchmark.name}
                        </Link>
                      </TableCell>
                      <TableCell className="tabular-nums">{runs}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={cn(badge.className)}>
                          {badge.label}
                        </Badge>
                      </TableCell>
                      <TableCell>
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
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {formatTimestamp(benchmark.created_at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

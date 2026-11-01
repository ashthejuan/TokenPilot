"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Chapter } from "@/components/Chapter";
import { NewBenchmarkForm } from "@/components/NewBenchmarkForm";
import { PageHeader } from "@/components/PageHeader";
import { SavingsBadge } from "@/components/SavingsBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiDelete, apiGet } from "@/lib/api";
import {
  benchmarkStatus,
  latestComparison,
  type BenchmarkDetail,
  type BenchmarkOut,
  type BenchmarkStatus,
  type ComparisonOut,
} from "@/lib/benchmarks";
import { formatTimestamp } from "@/lib/format";
import { PAGE_SHELL } from "@/lib/layout";
import { cn } from "@/lib/utils";

const STATUS_BADGE: Record<BenchmarkStatus, { label: string; className: string }> = {
  empty: { label: "No runs yet", className: "border-border bg-muted text-muted-foreground" },
  running: {
    label: "Running",
    className: "border-transparent bg-blue-500/15 text-blue-800 dark:text-blue-200",
  },
  done: { label: "Completed", className: "border-transparent bg-secondary text-secondary-foreground" },
};

type BenchmarkRow = {
  benchmark: BenchmarkOut;
  runs: number;
  status: BenchmarkStatus;
  latest: ComparisonOut | null;
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
  const [rows, setRows] = useState<BenchmarkRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const benchmarks = await apiGet<BenchmarkOut[]>("api/v1/benchmarks");
      const details = await Promise.all(
        benchmarks.map(async (benchmark) => {
          const [detail, comparisons] = await Promise.all([
            apiGet<BenchmarkDetail>(`api/v1/benchmarks/${benchmark.id}`),
            apiGet<ComparisonOut[]>(`api/v1/benchmarks/${benchmark.id}/comparisons`),
          ]);
          return { detail, comparisons };
        }),
      );
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
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function confirmDeleteBenchmark(benchmark: BenchmarkOut) {
    if (deletingId !== null) return;
    toast(`Delete “${benchmark.name}”?`, {
      id: `delete-benchmark-${benchmark.id}`,
      description: "Runs and comparisons for this experiment are removed.",
      duration: Infinity,
      action: {
        label: "Delete",
        onClick: () => {
          void performDelete(benchmark);
        },
      },
      cancel: {
        label: "Cancel",
        onClick: () => toast.dismiss(`delete-benchmark-${benchmark.id}`),
      },
    });
  }

  async function performDelete(benchmark: BenchmarkOut) {
    if (deletingId !== null) return;
    toast.dismiss(`delete-benchmark-${benchmark.id}`);
    setDeletingId(benchmark.id);
    setError(null);
    const loadingId = toast.loading(`Deleting “${benchmark.name}”…`);
    try {
      await apiDelete<null>(`api/v1/benchmarks/${benchmark.id}`);
      await refresh();
      toast.success(`Deleted “${benchmark.name}”`, { id: loadingId });
    } catch (err: unknown) {
      const message = errorText(err);
      setError(message);
      toast.error(message, { id: loadingId });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className={PAGE_SHELL}>
      <PageHeader
        title="Benchmarks"
        actions={
          <Button
            className="pressable"
            size="sm"
            variant={showForm ? "secondary" : "default"}
            onClick={() => setShowForm((open) => !open)}
            disabled={deletingId !== null}
          >
            {showForm ? "Close" : "New benchmark"}
          </Button>
        }
      />

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}

      {showForm ? (
        <Chapter title="New benchmark">
          <NewBenchmarkForm onCreated={(id) => router.push(`/benchmarks/${id}`)} />
        </Chapter>
      ) : null}

      <Chapter title="Benchmarks">
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
                <TableHead className="w-[1%] text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
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
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="destructive"
                        size="sm"
                        className="pressable"
                        disabled={deletingId !== null}
                        aria-label={`Delete benchmark ${benchmark.name}`}
                        onClick={() => confirmDeleteBenchmark(benchmark)}
                      >
                        {deletingId === benchmark.id ? "Deleting…" : "Delete"}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Chapter>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Chapter } from "@/components/Chapter";
import { ListPagination } from "@/components/ListPagination";
import { PageHeader } from "@/components/PageHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiGet, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/format";
import { impactLabel, insightListFilterKey, pollJob, ruleLabel } from "@/lib/insights";
import { PAGE_SHELL } from "@/lib/layout";
import {
  LIST_PAGE_SIZE,
  advanceCursorStack,
  pageCursor,
  resetCursorStack,
} from "@/lib/pagination";
import { shouldCommitFetch, shouldCommitLoadMore } from "@/lib/sessions";

type InsightOut = components["schemas"]["InsightOut"];
type PagedInsights = components["schemas"]["Paged_InsightOut_"];
type AnalyzeAccepted = components["schemas"]["AnalyzeAccepted"];
type JobOut = components["schemas"]["JobOut"];
type InsightStatus = InsightOut["status"] | "";
type Severity = InsightOut["severity"] | "";

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

const RULE_OPTIONS = [
  "repeated_request",
  "retry_amplification",
  "repeated_context",
  "unsuccessful_task",
  "context_ratio",
  "runaway_session",
  "model_inefficiency",
] as const;

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "proxy_not_configured") {
      return "The web server has no local token. Start it with `make dev-web`.";
    }
    if (error.code === "upstream_unreachable" || error.code === "upstream_timeout") {
      return "The TokenPilot API is not answering. Start it with `make dev-api`.";
    }
    if (error.code === "job_timeout") {
      return "Analysis timed out. Try again.";
    }
    return `${error.message} (${error.code})`;
  }
  return "Could not reach the TokenPilot web server.";
}

function scopeHref(insight: InsightOut): string | null {
  if (insight.session_id) return `/sessions/${insight.session_id}`;
  return null;
}

function scopeLabel(insight: InsightOut): string {
  if (insight.session_id) return insight.session_id.slice(0, 8);
  if (insight.project_id) return insight.project_id.slice(0, 8);
  return "—";
}

export default function InsightsPage() {
  const [status, setStatus] = useState<InsightStatus>("new");
  const [severity, setSeverity] = useState<Severity>("");
  const [ruleId, setRuleId] = useState("");
  const [items, setItems] = useState<InsightOut[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const filterGenerationRef = useRef(0);
  const filterKey = insightListFilterKey({ status, severity, ruleId });
  const filterKeyRef = useRef(filterKey);
  filterKeyRef.current = filterKey;

  const fetchPage = useCallback(
    async (
      cursor: string | null,
      filters: { status: InsightStatus; severity: Severity; ruleId: string },
    ) => {
      const params: Record<string, string> = { limit: String(LIST_PAGE_SIZE) };
      if (filters.status) params.status = filters.status;
      if (filters.severity) params.severity = filters.severity;
      if (filters.ruleId) params.rule_id = filters.ruleId;
      if (cursor) params.cursor = cursor;
      return apiGet<PagedInsights>("api/v1/insights", params);
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    const generation = ++filterGenerationRef.current;
    const requestFilter = filterKey;
    const cursor = pageCursor(cursorStack, pageIndex);
    setLoading(true);
    fetchPage(cursor, { status, severity, ruleId })
      .then((page) => {
        if (!shouldCommitFetch(cancelled)) return;
        if (
          !shouldCommitLoadMore(
            { generation, filter: requestFilter },
            { generation: filterGenerationRef.current, filter: filterKeyRef.current },
          )
        ) {
          return;
        }
        setItems(page.items);
        setNextCursor(page.next_cursor ?? null);
        setError(null);
      })
      .catch((err: unknown) => {
        if (
          shouldCommitFetch(cancelled) &&
          shouldCommitLoadMore(
            { generation, filter: requestFilter },
            { generation: filterGenerationRef.current, filter: filterKeyRef.current },
          )
        ) {
          setError(errorText(err));
        }
      })
      .finally(() => {
        if (shouldCommitFetch(cancelled) && generation === filterGenerationRef.current) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPage, refreshKey, status, severity, ruleId, filterKey, pageIndex, cursorStack]);

  function resetPaging() {
    const reset = resetCursorStack();
    setCursorStack(reset.cursorStack);
    setPageIndex(reset.pageIndex);
    setNextCursor(null);
  }

  function changeStatus(next: InsightStatus) {
    setStatus(next);
    resetPaging();
  }

  function changeSeverity(next: Severity) {
    setSeverity(next);
    resetPaging();
  }

  function changeRuleId(next: string) {
    setRuleId(next);
    resetPaging();
  }

  function goPrev() {
    if (pageIndex <= 0) return;
    setPageIndex(pageIndex - 1);
  }

  function goNext() {
    const advanced = advanceCursorStack(cursorStack, pageIndex, nextCursor);
    if (!advanced) return;
    setCursorStack(advanced.cursorStack);
    setPageIndex(advanced.pageIndex);
  }

  async function runAnalysis() {
    if (analyzing) return;
    setAnalyzing(true);
    setJobStatus("queued");
    setJobError(null);
    setError(null);
    try {
      const accepted = await apiSend<AnalyzeAccepted>("POST", "api/v1/insights/analyze", {});
      setJobStatus("running");
      const job: JobOut = await pollJob(accepted.job_id, { intervalMs: 1000, timeoutMs: 60000 });
      setJobStatus(job.status);
      if (job.status === "failed") {
        setJobError(job.error ?? "Analysis failed.");
      } else {
        setJobError(null);
        resetPaging();
        setRefreshKey((key) => key + 1);
      }
    } catch (err: unknown) {
      setJobStatus("failed");
      setJobError(errorText(err));
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <div className={PAGE_SHELL}>
      <PageHeader
        title="Insights"
        actions={
          <div className="flex flex-wrap items-center gap-3">
            {jobStatus ? (
              <p className="text-sm text-muted-foreground" aria-live="polite">
                Job: {jobStatus}
              </p>
            ) : null}
            <Button size="sm" onClick={() => void runAnalysis()} disabled={analyzing}>
              {analyzing ? "Running…" : "Run analysis"}
            </Button>
          </div>
        }
      />

      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Status
          <select
            className={SELECT_CLASS}
            value={status}
            onChange={(e) => changeStatus(e.target.value as InsightStatus)}
          >
            <option value="">All statuses</option>
            <option value="new">New</option>
            <option value="reviewed">Reviewed</option>
            <option value="dismissed">Dismissed</option>
            <option value="tested">Tested</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Severity
          <select
            className={SELECT_CLASS}
            value={severity}
            onChange={(e) => changeSeverity(e.target.value as Severity)}
          >
            <option value="">All severities</option>
            <option value="informational">Informational</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Rule
          <select
            className={SELECT_CLASS}
            value={ruleId}
            onChange={(e) => changeRuleId(e.target.value)}
          >
            <option value="">All rules</option>
            {RULE_OPTIONS.map((rule) => (
              <option key={rule} value={rule}>
                {rule}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}

      {jobError ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {jobError}
        </div>
      ) : null}

      <Chapter title="Insights">
        <div className="space-y-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading insights…</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No insights match this filter.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Severity</TableHead>
                  <TableHead>Rule</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead>Impact</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((insight) => {
                  const scope = scopeHref(insight);
                  const label = ruleLabel(insight.rule_id, insight.rule_version);
                  return (
                    <TableRow key={insight.id}>
                      <TableCell>
                        <SeverityBadge severity={insight.severity} />
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/insights/${insight.id}`}
                          className="font-mono text-xs underline-offset-4 hover:underline"
                        >
                          {label}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-64 truncate" title={insight.title}>
                        <Link
                          href={`/insights/${insight.id}`}
                          className="underline-offset-4 hover:underline"
                        >
                          {insight.title}
                        </Link>
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {impactLabel(insight.estimated_impact, insight.impact_currency)}
                      </TableCell>
                      <TableCell className="max-w-32 truncate font-mono text-xs">
                        {scope ? (
                          <Link
                            href={scope}
                            className="underline-offset-4 hover:underline"
                            title={insight.session_id ?? undefined}
                          >
                            {scopeLabel(insight)}
                          </Link>
                        ) : (
                          <span title={insight.project_id ?? undefined}>{scopeLabel(insight)}</span>
                        )}
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {formatTimestamp(insight.updated_at ?? insight.created_at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}

          {!loading ? (
            <ListPagination
              pageIndex={pageIndex}
              nextCursor={nextCursor}
              loading={loading}
              onPrev={goPrev}
              onNext={goNext}
            />
          ) : null}
        </div>
      </Chapter>
    </div>
  );
}

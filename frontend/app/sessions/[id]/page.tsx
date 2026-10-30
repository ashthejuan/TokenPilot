"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Chapter } from "@/components/Chapter";
import { CostValue } from "@/components/CostValue";
import { OutcomeSetter } from "@/components/OutcomeSetter";
import { PageHeader } from "@/components/PageHeader";
import { RequestTimeline } from "@/components/RequestTimeline";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiGet } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { formatCount, formatTimestamp } from "@/lib/format";
import { PAGE_SHELL } from "@/lib/layout";
import { contextSignals, eventsTruncated, formatTokens } from "@/lib/sessions";

type SessionDetail = components["schemas"]["SessionDetail"];
type InsightOut = components["schemas"]["InsightOut"];
type PagedInsights = components["schemas"]["Paged_InsightOut_"];

const OUTCOME_LABEL: Record<SessionDetail["outcome"], string> = {
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
    if (error.status === 404) return "Session not found.";
    return `${error.message} (${error.code})`;
  }
  return "Could not reach the TokenPilot web server.";
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium tabular-nums" title={typeof children === "string" ? children : undefined}>
        {children}
      </p>
    </div>
  );
}

function observationLabel(measurements: InsightOut["measurements"]): string | null {
  const value = measurements.observation;
  if (value === "hash_only") return "hash-only";
  if (typeof value === "string" && value.length > 0) return value;
  return null;
}

export default function SessionDetailPage() {
  const params = useParams<{ id: string }>();
  const sessionId = params.id;

  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [insights, setInsights] = useState<InsightOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const refetch = useCallback(() => setRefreshKey((key) => key + 1), []);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      apiGet<SessionDetail>(`api/v1/sessions/${sessionId}`),
      apiGet<PagedInsights>("api/v1/insights", { session_id: sessionId }),
    ])
      .then(([nextDetail, nextInsights]) => {
        if (cancelled) return;
        setDetail(nextDetail);
        setInsights(nextInsights.items);
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
  }, [sessionId, refreshKey]);

  const signals = contextSignals(insights);
  const truncated = detail
    ? eventsTruncated(detail.session.request_count, detail.events.length)
    : false;

  return (
    <div className={PAGE_SHELL}>
      <p className="text-sm text-muted-foreground">
        <Link href="/sessions" className="underline-offset-4 hover:underline">
          Sessions
        </Link>
      </p>

      <PageHeader title="Session" description={sessionId} />

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}

      {loading && detail === null ? (
        <p className="text-sm text-muted-foreground">Loading session…</p>
      ) : null}

      {detail ? (
        <div className={loading ? "space-y-10 opacity-60" : "space-y-10"}>
          <Chapter title="Summary">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Started">{formatTimestamp(detail.session.started_at)}</Stat>
              <Stat label="Ended">
                {detail.session.ended_at ? formatTimestamp(detail.session.ended_at) : "—"}
              </Stat>
              <Stat label="Project">
                {detail.session.project_id ?? (
                  <span className="italic text-muted-foreground">Unattributed</span>
                )}
              </Stat>
              <Stat label="Source">{detail.session.source}</Stat>
              <Stat label="Requests">{formatCount(detail.session.request_count)}</Stat>
              <Stat label="Cost">
                <CostValue
                  value={detail.session.total_estimated_cost ?? null}
                  currency={detail.session.currency ?? null}
                />
              </Stat>
              <Stat label="External id">
                {detail.session.external_session_id ?? "—"}
              </Stat>
            </div>
          </Chapter>

          <Chapter title="Outcome" description="Provenance and manual override">
            <div className="flex flex-wrap items-end gap-6">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Current</p>
                <Badge variant="outline">{OUTCOME_LABEL[detail.outcome]}</Badge>
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Source</p>
                <p className="text-sm">{detail.outcome_source ?? "—"}</p>
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Set outcome</p>
                <OutcomeSetter
                  sessionId={detail.session.id}
                  outcome={detail.outcome}
                  onUpdated={refetch}
                />
              </div>
            </div>
          </Chapter>

          <Chapter title="Model breakdown">
            {detail.by_model.length === 0 ? (
              <p className="text-sm text-muted-foreground">No model usage recorded.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead className="text-right">Requests</TableHead>
                    <TableHead className="text-right">Tokens in</TableHead>
                    <TableHead className="text-right">Tokens out</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.by_model.map((row) => (
                    <TableRow key={row.model_id}>
                      <TableCell className="max-w-48 truncate font-mono text-xs" title={row.model_id}>
                        {row.model_id}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatCount(row.request_count)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {formatTokens(row.input_tokens)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {formatTokens(row.output_tokens)}
                      </TableCell>
                      <TableCell className="text-right">
                        <CostValue
                          value={row.estimated_cost ?? null}
                          currency={row.currency ?? null}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Chapter>

          <Chapter title="Request timeline">
            <RequestTimeline
              events={detail.events}
              requestCount={detail.session.request_count}
              truncated={truncated}
            />
          </Chapter>

          <Chapter
            title="Repeated-context signals"
            description="Hash-only observations; this is not necessarily avoidable."
          >
            {signals.length === 0 ? (
              <p className="text-sm text-muted-foreground">No repeated-context signals for this session.</p>
            ) : (
              <ul className="space-y-3">
                {signals.map((signal) => {
                  const label = observationLabel(signal.measurements);
                  return (
                    <li key={signal.id} className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <SeverityBadge severity={signal.severity} />
                        {label ? (
                          <Badge variant="outline" className="font-normal">
                            {label}
                          </Badge>
                        ) : null}
                        <span className="text-sm font-medium">{signal.title}</span>
                      </div>
                      <p className="text-sm text-muted-foreground">{signal.summary}</p>
                    </li>
                  );
                })}
              </ul>
            )}
          </Chapter>

          <Chapter title="Related insights">
            {insights.length === 0 ? (
              <p className="text-sm text-muted-foreground">No insights linked to this session.</p>
            ) : (
              <ul className="space-y-2">
                {insights.map((insight) => (
                  <li key={insight.id} className="flex flex-wrap items-center gap-2">
                    <SeverityBadge severity={insight.severity} />
                    <Link
                      href={`/insights/${insight.id}`}
                      className="text-sm underline-offset-4 hover:underline"
                    >
                      {insight.title}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Chapter>
        </div>
      ) : null}
    </div>
  );
}

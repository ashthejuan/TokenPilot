"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { CostValue } from "@/components/CostValue";
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
import type { components } from "@/lib/api-types";
import { formatCount, formatTimestamp } from "@/lib/format";
import { shouldCommitFetch } from "@/lib/sessions";

type SessionSummary = components["schemas"]["SessionSummary"];
type PagedSessions = components["schemas"]["Paged_SessionSummary_"];
type Outcome = SessionSummary["outcome"] | "";

const OUTCOME_LABEL: Record<SessionSummary["outcome"], string> = {
  success: "Success",
  failure: "Failure",
  abandoned: "Abandoned",
  unknown: "Unknown",
};

const OUTCOME_VARIANT: Record<
  SessionSummary["outcome"],
  "default" | "secondary" | "outline" | "destructive"
> = {
  success: "secondary",
  failure: "destructive",
  abandoned: "outline",
  unknown: "outline",
};

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

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

export default function SessionsPage() {
  const [outcome, setOutcome] = useState<Outcome>("");
  const [items, setItems] = useState<SessionSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPage = useCallback(async (cursor: string | null, outcomeFilter: Outcome) => {
    const params: Record<string, string> = {};
    if (outcomeFilter) params.outcome = outcomeFilter;
    if (cursor) params.cursor = cursor;
    return apiGet<PagedSessions>("api/v1/sessions", params);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setItems([]);
    setNextCursor(null);
    fetchPage(null, outcome)
      .then((page) => {
        if (!shouldCommitFetch(cancelled)) return;
        setItems(page.items);
        setNextCursor(page.next_cursor ?? null);
        setError(null);
      })
      .catch((err: unknown) => {
        if (shouldCommitFetch(cancelled)) setError(errorText(err));
      })
      .finally(() => {
        if (shouldCommitFetch(cancelled)) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [outcome, fetchPage]);

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await fetchPage(nextCursor, outcome);
      setItems((current) => [...current, ...page.items]);
      setNextCursor(page.next_cursor ?? null);
      setError(null);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-2xl font-semibold">Sessions</h1>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Outcome
          <select
            className={SELECT_CLASS}
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as Outcome)}
          >
            <option value="">All outcomes</option>
            <option value="success">Success</option>
            <option value="failure">Failure</option>
            <option value="abandoned">Abandoned</option>
            <option value="unknown">Unknown</option>
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

      <Card>
        <CardHeader>
          <CardTitle>All sessions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading sessions…</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No sessions match this filter.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Started</TableHead>
                  <TableHead>Project</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="text-right">Requests</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead>Outcome</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((session) => (
                  <TableRow key={session.id}>
                    <TableCell>
                      <Link
                        href={`/sessions/${session.id}`}
                        className="tabular-nums text-foreground underline-offset-4 hover:underline"
                        title={session.id}
                      >
                        {formatTimestamp(session.started_at)}
                      </Link>
                    </TableCell>
                    <TableCell className="max-w-40 truncate" title={session.project_id ?? undefined}>
                      {session.project_id ?? (
                        <span className="italic text-muted-foreground">Unattributed</span>
                      )}
                    </TableCell>
                    <TableCell className="max-w-32 truncate" title={session.source}>
                      {session.source}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCount(session.request_count)}
                    </TableCell>
                    <TableCell className="text-right">
                      <CostValue
                        value={session.total_estimated_cost ?? null}
                        currency={session.currency ?? null}
                      />
                    </TableCell>
                    <TableCell>
                      <Badge variant={OUTCOME_VARIANT[session.outcome]}>
                        {OUTCOME_LABEL[session.outcome]}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {!loading && nextCursor ? (
            <Button variant="outline" size="sm" onClick={() => void loadMore()} disabled={loadingMore}>
              {loadingMore ? "Loading…" : "Load more"}
            </Button>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Chapter } from "@/components/Chapter";
import { CostValue } from "@/components/CostValue";
import { ListPagination } from "@/components/ListPagination";
import { PageHeader } from "@/components/PageHeader";
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
import {
  LIST_PAGE_SIZE,
  advanceCursorStack,
  pageCursor,
  resetCursorStack,
} from "@/lib/pagination";
import { shouldCommitFetch, shouldCommitLoadMore } from "@/lib/sessions";

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
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const filterGenerationRef = useRef(0);
  const outcomeRef = useRef(outcome);
  outcomeRef.current = outcome;

  const fetchPage = useCallback(async (cursor: string | null, outcomeFilter: Outcome) => {
    const params: Record<string, string> = { limit: String(LIST_PAGE_SIZE) };
    if (outcomeFilter) params.outcome = outcomeFilter;
    if (cursor) params.cursor = cursor;
    return apiGet<PagedSessions>("api/v1/sessions", params);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const generation = ++filterGenerationRef.current;
    const requestFilter = outcome;
    const cursor = pageCursor(cursorStack, pageIndex);
    setLoading(true);
    fetchPage(cursor, outcome)
      .then((page) => {
        if (!shouldCommitFetch(cancelled)) return;
        if (
          !shouldCommitLoadMore(
            { generation, filter: requestFilter },
            { generation: filterGenerationRef.current, filter: outcomeRef.current },
          )
        ) {
          return;
        }
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
  }, [outcome, pageIndex, cursorStack, fetchPage]);

  function changeOutcome(next: Outcome) {
    setOutcome(next);
    const reset = resetCursorStack();
    setCursorStack(reset.cursorStack);
    setPageIndex(reset.pageIndex);
    setNextCursor(null);
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

  return (
    <div className={PAGE_SHELL}>
      <PageHeader
        title="Sessions"
        actions={
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Outcome
            <select
              className={SELECT_CLASS}
              value={outcome}
              onChange={(e) => changeOutcome(e.target.value as Outcome)}
            >
              <option value="">All outcomes</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
              <option value="abandoned">Abandoned</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
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

      <Chapter title="All sessions">
        <div className="space-y-4">
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

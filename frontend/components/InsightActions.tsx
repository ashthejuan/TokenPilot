"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { DEFAULT_INSIGHT_TASK_SPEC } from "@/lib/reports";

type InsightOut = components["schemas"]["InsightOut"];
type InsightStatus = InsightOut["status"];
type BenchmarkOut = components["schemas"]["BenchmarkOut"];
type InsightBenchmarkCreate = components["schemas"]["InsightBenchmarkCreate"];

type InsightActionsProps = {
  insightId: string;
  status: InsightStatus;
  onUpdated: (insight: InsightOut) => void;
  onInvestigate?: () => void;
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
  return "Could not update insight status.";
}

export function InsightActions({ insightId, status, onUpdated, onInvestigate }: InsightActionsProps) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function patchStatus(next: InsightStatus, actionKey: string) {
    if (busy) return;
    setBusy(actionKey);
    setError(null);
    try {
      const updated = await apiSend<InsightOut>("PATCH", `api/v1/insights/${insightId}`, {
        status: next,
      });
      onUpdated(updated);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  async function createBenchmark() {
    if (busy) return;
    setBusy("benchmark");
    setError(null);
    const body: InsightBenchmarkCreate = {
      task_spec: DEFAULT_INSIGHT_TASK_SPEC,
    };
    try {
      const created = await apiSend<BenchmarkOut>(
        "POST",
        `api/v1/insights/${insightId}/benchmark`,
        body,
      );
      router.push(`/benchmarks/${created.id}`);
    } catch (err: unknown) {
      setError(errorText(err));
      setBusy(null);
    }
  }

  return (
    <TooltipProvider>
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {status !== "reviewed" ? (
            <Button
              className="pressable"
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() => void patchStatus("reviewed", "reviewed")}
            >
              {busy === "reviewed" ? "Saving…" : "Mark reviewed"}
            </Button>
          ) : null}
          {status !== "dismissed" ? (
            <Button
              className="pressable"
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() => void patchStatus("dismissed", "dismissed")}
            >
              {busy === "dismissed" ? "Saving…" : "Dismiss"}
            </Button>
          ) : null}
          {status !== "new" ? (
            <Button
              className="pressable"
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() => void patchStatus("new", "reopen")}
            >
              {busy === "reopen" ? "Saving…" : "Reopen"}
            </Button>
          ) : null}
          {onInvestigate ? (
            <Button
              className="pressable"
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={onInvestigate}
            >
              Investigate
            </Button>
          ) : (
            <Tooltip>
              <TooltipTrigger delay={0} render={<span className="inline-flex cursor-not-allowed" />}>
                <Button size="sm" variant="outline" disabled>
                  Investigate
                </Button>
              </TooltipTrigger>
              <TooltipContent>Phase 3</TooltipContent>
            </Tooltip>
          )}
          <Button
            className="pressable"
            size="sm"
            variant="outline"
            disabled={busy !== null}
            onClick={() => void createBenchmark()}
          >
            {busy === "benchmark" ? "Creating…" : "Create benchmark"}
          </Button>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </TooltipProvider>
  );
}

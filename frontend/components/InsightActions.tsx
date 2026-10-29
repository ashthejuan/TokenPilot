"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";

type InsightOut = components["schemas"]["InsightOut"];
type InsightStatus = InsightOut["status"];

type InsightActionsProps = {
  insightId: string;
  status: InsightStatus;
  onUpdated: (insight: InsightOut) => void;
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.message} (${error.code})`;
  return "Could not update insight status.";
}

export function InsightActions({ insightId, status, onUpdated }: InsightActionsProps) {
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

  return (
    <TooltipProvider>
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {status !== "reviewed" ? (
            <Button
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
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() => void patchStatus("new", "reopen")}
            >
              {busy === "reopen" ? "Saving…" : "Reopen"}
            </Button>
          ) : null}
          <Tooltip>
            <TooltipTrigger delay={0} render={<span className="inline-flex cursor-not-allowed" />}>
              <Button size="sm" variant="outline" disabled>
                Investigate
              </Button>
            </TooltipTrigger>
            <TooltipContent>Phase 3</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger delay={0} render={<span className="inline-flex cursor-not-allowed" />}>
              <Button size="sm" variant="outline" disabled>
                Create benchmark
              </Button>
            </TooltipTrigger>
            <TooltipContent>Phase 5</TooltipContent>
          </Tooltip>
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

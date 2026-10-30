"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { buildInsightBenchmarkCreateBody, suggestTaskSpecPath } from "@/lib/reports";

type InsightOut = components["schemas"]["InsightOut"];
type InsightStatus = InsightOut["status"];
type BenchmarkOut = components["schemas"]["BenchmarkOut"];

type InsightActionsProps = {
  insightId: string;
  status: InsightStatus;
  /** Project repository_path used as placeholder / "use demo" fill. */
  repositoryPath?: string | null;
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

export function InsightActions({
  insightId,
  status,
  repositoryPath = null,
  onUpdated,
  onInvestigate,
}: InsightActionsProps) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showBenchmarkForm, setShowBenchmarkForm] = useState(false);
  const [taskSpecPath, setTaskSpecPath] = useState("");
  const suggested = suggestTaskSpecPath(repositoryPath);

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
    let body;
    try {
      body = buildInsightBenchmarkCreateBody(taskSpecPath);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "task_spec_path is required");
      return;
    }
    setBusy("benchmark");
    setError(null);
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
            onClick={() => {
              setShowBenchmarkForm((open) => !open);
              setError(null);
              if (!taskSpecPath && suggested) setTaskSpecPath(suggested);
            }}
          >
            {showBenchmarkForm ? "Cancel benchmark" : "Create benchmark"}
          </Button>
        </div>
        {showBenchmarkForm ? (
          <div
            data-testid="create-benchmark-form"
            className="space-y-3 rounded-lg border border-border p-3"
          >
            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              Task spec path (required)
              <Input
                value={taskSpecPath}
                onChange={(e) => setTaskSpecPath(e.target.value)}
                placeholder={suggested || "/path/to/demo/benchmark_task.yaml"}
                disabled={busy !== null}
                aria-required
              />
            </label>
            <div className="flex flex-wrap gap-2">
              {suggested ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy !== null}
                  onClick={() => setTaskSpecPath(suggested)}
                >
                  Use offline demo spec
                </Button>
              ) : null}
              <Button
                className="pressable"
                size="sm"
                disabled={busy !== null || taskSpecPath.trim().length < 1}
                onClick={() => void createBenchmark()}
              >
                {busy === "benchmark" ? "Creating…" : "Create"}
              </Button>
            </div>
          </div>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </TooltipProvider>
  );
}

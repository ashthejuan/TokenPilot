"use client";

import { useState } from "react";

import { Chapter } from "@/components/Chapter";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiDelete } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { retentionBeforeParam } from "@/lib/settings";

type DataDeleteResponse = components["schemas"]["DataDeleteResponse"];

export function RetentionSection() {
  const [before, setBefore] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DataDeleteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    if (busy) return;
    const param = retentionBeforeParam(before);
    if (param === null) {
      setError("Pick a date and time first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await apiDelete<DataDeleteResponse>("api/v1/data", { before: param });
      setResult(response);
      setConfirming(false);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? `${err.message} (${err.code})` : "Could not delete data.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Chapter
      title="Retention"
      description="Deletes usage events older than the bound, plus their costs and excerpts. Insights, projects, sessions, and pricing are kept. This cannot be undone."
    >
      <div className="space-y-3" data-testid="retention-section">
        <label className="flex max-w-xs flex-col gap-1 text-xs font-medium text-muted-foreground">
          Delete events before (UTC)
          <Input type="datetime-local" value={before} onChange={(e) => setBefore(e.target.value)} />
        </label>
        {result ? (
          <p data-testid="retention-result" className="text-sm text-muted-foreground">
            Deleted {result.deleted_events} events, {result.deleted_excerpt_files} excerpt files,{" "}
            {result.deleted_worktrees} worktrees.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {confirming ? (
          <div className="flex gap-2">
            <Button size="sm" variant="destructive" disabled={busy} onClick={() => void remove()}>
              {busy ? "Deleting…" : "Confirm delete"}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
            Delete old data…
          </Button>
        )}
      </div>
    </Chapter>
  );
}

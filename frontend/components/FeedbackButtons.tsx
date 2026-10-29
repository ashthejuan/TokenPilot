"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";

type FeedbackVerdict = components["schemas"]["FeedbackRequest"]["verdict"];

type FeedbackButtonsProps = {
  insightId: string;
  onRecorded?: () => void;
};

const VERDICTS: { value: FeedbackVerdict; label: string }[] = [
  { value: "useful", label: "Useful" },
  { value: "not_useful", label: "Not useful" },
  { value: "not_applicable", label: "Not applicable" },
];

export function FeedbackButtons({ insightId, onRecorded }: FeedbackButtonsProps) {
  const [implemented, setImplemented] = useState(false);
  const [busy, setBusy] = useState<FeedbackVerdict | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<FeedbackVerdict | null>(null);

  async function send(verdict: FeedbackVerdict) {
    if (busy) return;
    setBusy(verdict);
    setError(null);
    try {
      await apiSend("POST", `api/v1/insights/${insightId}/feedback`, {
        verdict,
        implemented,
      });
      setRecorded(verdict);
      onRecorded?.();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? `${err.message} (${err.code})` : "Could not record feedback.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div data-testid="feedback-buttons" className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {VERDICTS.map(({ value, label }) => (
          <Button
            key={value}
            size="sm"
            variant={recorded === value ? "default" : "outline"}
            disabled={busy !== null}
            onClick={() => void send(value)}
          >
            {busy === value ? "Saving…" : label}
          </Button>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          checked={implemented}
          onChange={(event) => setImplemented(event.target.checked)}
        />
        I implemented this
      </label>
      {recorded ? (
        <p className="text-sm text-muted-foreground">Feedback recorded: {recorded}.</p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

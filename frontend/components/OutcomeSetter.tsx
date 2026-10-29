"use client";

import { useEffect, useState } from "react";

import { ApiError, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { outcomeSelectValue, reconcilePendingOutcome } from "@/lib/sessions";

type SessionOutcome = components["schemas"]["SessionUpdate"]["outcome"];
type SessionSummary = components["schemas"]["SessionSummary"];

const OUTCOMES: { value: SessionOutcome; label: string }[] = [
  { value: "success", label: "Success" },
  { value: "failure", label: "Failure" },
  { value: "abandoned", label: "Abandoned" },
  { value: "unknown", label: "Unknown" },
];

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 disabled:opacity-50";

type OutcomeSetterProps = {
  sessionId: string;
  outcome: SessionOutcome;
  onUpdated: () => void;
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.message} (${error.code})`;
  return "Could not update outcome.";
}

export function OutcomeSetter({ sessionId, outcome, onUpdated }: OutcomeSetterProps) {
  const [pending, setPending] = useState<SessionOutcome | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const display = outcomeSelectValue(outcome, pending);

  useEffect(() => {
    setPending((current) => reconcilePendingOutcome(outcome, current));
  }, [outcome]);

  async function handleChange(next: SessionOutcome) {
    if (next === display || saving) return;
    setPending(next);
    setSaving(true);
    setError(null);
    try {
      await apiSend<SessionSummary>("PATCH", `api/v1/sessions/${sessionId}`, { outcome: next });
      onUpdated();
    } catch (err: unknown) {
      setPending(null);
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-1">
      <select
        className={SELECT_CLASS}
        value={display}
        disabled={saving}
        aria-label="Session outcome"
        onChange={(e) => void handleChange(e.target.value as SessionOutcome)}
      >
        {OUTCOMES.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

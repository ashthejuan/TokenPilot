"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, apiGet, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { parseThresholdNumber } from "@/lib/settings";

type Thresholds = components["schemas"]["Thresholds-Output"];
type ThresholdsResponse = components["schemas"]["ThresholdsResponse"];

const FIELDS: { key: keyof Thresholds; label: string }[] = [
  { key: "repeat_window_s", label: "Repeat window (s)" },
  { key: "retry_min_attempts", label: "Retry min attempts" },
  { key: "unsuccessful_min_cost", label: "Unsuccessful min cost" },
  { key: "runaway_max_requests", label: "Runaway max requests" },
  { key: "runaway_max_cost", label: "Runaway max cost" },
  { key: "runaway_max_duration_min", label: "Runaway max duration (min)" },
  { key: "runaway_max_retries", label: "Runaway max retries" },
  { key: "open_session_grace_min", label: "Open session grace (min)" },
  { key: "context_min_chars", label: "Context min chars" },
  { key: "context_repeat_min_occurrences", label: "Context repeat min occurrences" },
  { key: "context_medium_repeated_tokens", label: "Context medium repeated tokens" },
  { key: "ratio_threshold", label: "Ratio threshold" },
  { key: "ratio_min_input_tokens", label: "Ratio min input tokens" },
  { key: "ratio_low_min_events", label: "Ratio low min events" },
  { key: "severity_high_cost", label: "Severity high cost" },
  { key: "severity_medium_cost", label: "Severity medium cost" },
];

export function ThresholdsSection() {
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<Thresholds>("api/v1/settings/thresholds")
      .then((next) => {
        if (cancelled) return;
        setDraft(Object.fromEntries(FIELDS.map(({ key }) => [key, String(next[key])])));
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.message} (${err.code})` : "Could not load thresholds.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function save() {
    if (!draft || busy) return;
    const parsed: Record<string, number> = {};
    for (const { key } of FIELDS) {
      const value = parseThresholdNumber(draft[key] ?? "");
      if (value === null) {
        setError(`Threshold ${key} needs a finite number.`);
        return;
      }
      parsed[key] = value;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await apiSend<ThresholdsResponse>("PUT", "api/v1/settings/thresholds", parsed);
      setDraft(Object.fromEntries(FIELDS.map(({ key }) => [key, String(response.thresholds[key])])));
      setSaved(response.reanalysis_required);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? `${err.message} (${err.code})` : "Could not save thresholds.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-testid="thresholds-section">
      <CardHeader>
        <CardTitle>Detector thresholds</CardTitle>
        <CardDescription>Saving replaces the whole set. Stored insights are not re-run.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {draft === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {FIELDS.map(({ key, label }) => (
              <label key={key} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                {label}
                <Input
                  type="number"
                  value={draft[key] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                />
              </label>
            ))}
          </div>
        )}
        {saved ? (
          <p className="text-sm text-muted-foreground">
            Saved. Detectors do not re-run on their own — run analysis again to apply the new thresholds.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <Button size="sm" disabled={draft === null || busy} onClick={() => void save()}>
          {busy ? "Saving…" : "Save thresholds"}
        </Button>
      </CardContent>
    </Card>
  );
}

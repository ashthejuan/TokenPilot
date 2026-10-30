"use client";

import { useEffect, useState } from "react";

import { Chapter } from "@/components/Chapter";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiGet, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";

type PricingVersionCreate = components["schemas"]["PricingVersionCreate"];
type PricingVersionOut = components["schemas"]["PricingVersionOut"];
type RepriceResponse = components["schemas"]["RepriceResponse"];

function priceLabel(value: number | null): string {
  return value === null ? "—" : String(value);
}

export function PricingSection() {
  const [versions, setVersions] = useState<PricingVersionOut[] | null>(null);
  const [form, setForm] = useState({
    provider: "",
    model_id: "",
    currency: "USD",
    input_price_per_million: "",
    output_price_per_million: "",
    pricing_source: "",
  });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<PricingVersionOut[]>("api/v1/settings/pricing")
      .then((next) => {
        if (!cancelled) setVersions(next);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.message} (${err.code})` : "Could not load pricing.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function set(key: keyof typeof form, value: string) {
    setForm({ ...form, [key]: value });
  }

  async function submit() {
    if (busy) return;
    if (!form.provider.trim() || !form.model_id.trim() || !form.currency.trim()) {
      setError("Provider, model, and currency are required.");
      return;
    }
    const body: PricingVersionCreate = {
      provider: form.provider.trim(),
      model_id: form.model_id.trim(),
      currency: form.currency.trim(),
      input_price_per_million: form.input_price_per_million.trim() === "" ? null : Number(form.input_price_per_million),
      output_price_per_million: form.output_price_per_million.trim() === "" ? null : Number(form.output_price_per_million),
      pricing_source: form.pricing_source.trim() === "" ? null : form.pricing_source.trim(),
    };
    if (
      (typeof body.input_price_per_million === "number" && !Number.isFinite(body.input_price_per_million)) ||
      (typeof body.output_price_per_million === "number" && !Number.isFinite(body.output_price_per_million))
    ) {
      setError("Prices must be finite numbers.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiSend<RepriceResponse>("PUT", "api/v1/settings/pricing", body);
      const next = await apiGet<PricingVersionOut[]>("api/v1/settings/pricing");
      setVersions(next);
      setNotice(`Saved version ${response.version.id}; repriced ${response.repriced} events.`);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? `${err.message} (${err.code})` : "Could not save pricing.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Chapter
      title="Pricing"
      description="A PUT never edits in place: it versions. A new version reprices past events automatically."
    >
      <div className="space-y-4" data-testid="pricing-section">
        {versions === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No pricing versions.</p>
        ) : (
          <ul className="space-y-2">
            {versions.map((version) => (
              <li key={version.id} className="rounded-md border px-3 py-2 text-sm">
                <span className="font-medium">
                  {version.provider} / {version.model_id}
                </span>{" "}
                <span className="text-muted-foreground">
                  {version.currency} in {priceLabel(version.input_price_per_million)} / out{" "}
                  {priceLabel(version.output_price_per_million)} per million · since {version.valid_from}
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Provider
            <Input value={form.provider} onChange={(e) => set("provider", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Model
            <Input value={form.model_id} onChange={(e) => set("model_id", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Currency
            <Input value={form.currency} onChange={(e) => set("currency", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Source URL
            <Input value={form.pricing_source} onChange={(e) => set("pricing_source", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Input per million
            <Input
              type="number"
              value={form.input_price_per_million}
              onChange={(e) => set("input_price_per_million", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Output per million
            <Input
              type="number"
              value={form.output_price_per_million}
              onChange={(e) => set("output_price_per_million", e.target.value)}
            />
          </label>
        </div>
        {notice ? <p className="text-sm text-muted-foreground">{notice}</p> : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <Button size="sm" disabled={busy} onClick={() => void submit()}>
          {busy ? "Saving…" : "Save pricing version"}
        </Button>
      </div>
    </Chapter>
  );
}

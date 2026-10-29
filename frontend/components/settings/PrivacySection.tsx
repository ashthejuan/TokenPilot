"use client";

import { useEffect, useState } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiGet } from "@/lib/api";
import type { components } from "@/lib/api-types";

type PrivacyOut = components["schemas"]["PrivacyOut"];

function boolLabel(value: boolean): string {
  return value ? "Yes" : "No";
}

export function PrivacySection() {
  const [privacy, setPrivacy] = useState<PrivacyOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<PrivacyOut>("api/v1/settings/privacy")
      .then((next) => {
        if (!cancelled) setPrivacy(next);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.message} (${err.code})` : "Could not load privacy settings.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Card data-testid="privacy-section">
      <CardHeader>
        <CardTitle>Connection &amp; privacy</CardTitle>
        <CardDescription>
          Read-only. To change these values, edit `.env` and restart the API.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : privacy === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Local token configured</dt>
            <dd>{boolLabel(privacy.local_token_configured)}</dd>
            <dt className="text-muted-foreground">Upstream URL</dt>
            <dd className="break-all">{privacy.upstream_base_url}</dd>
            <dt className="text-muted-foreground">Investigator model</dt>
            <dd className="break-all">{privacy.investigator_model}</dd>
            <dt className="text-muted-foreground">Store content</dt>
            <dd>{boolLabel(privacy.store_content)}</dd>
            <dt className="text-muted-foreground">Allow content transmission</dt>
            <dd>{boolLabel(privacy.allow_content_transmission)}</dd>
          </dl>
        )}
        {privacy?.contributor_training ? (
          <p data-testid="privacy-contributor-note" className="mt-3 text-sm text-muted-foreground">
            Contributor mode: Meta may use the content you send to train future
            models. Investigations stay metadata-only unless content
            transmission and storage are both enabled.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

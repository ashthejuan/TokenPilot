"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { components } from "@/lib/api-types";

type InvestigationPreviewOut = components["schemas"]["InvestigationPreviewOut"];

type DisclosureDialogProps = {
  preview: InvestigationPreviewOut;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
};

export function DisclosureDialog({
  preview,
  busy,
  error,
  onConfirm,
  onCancel,
}: DisclosureDialogProps) {
  const [showBundle, setShowBundle] = useState(false);

  return (
    <div
      data-testid="disclosure-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="Disclosure before investigating"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onCancel}
    >
      <Card
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto"
        // Clicks inside the card must not close the dialog.
        onClick={(event) => event.stopPropagation()}
      >
        <CardHeader>
          <CardTitle>Before sending to Meta</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {preview.disclosure_lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Destination</dt>
            <dd className="break-all">{preview.destination}</dd>
            <dt className="text-muted-foreground">Model</dt>
            <dd className="break-all">{preview.model}</dd>
            <dt className="text-muted-foreground">Content</dt>
            <dd>{preview.contains_content ? "includes request excerpts" : "metadata only"}</dd>
          </dl>
          {preview.contributor_training ? (
            <p
              data-testid="contributor-warning"
              className="rounded-md border border-amber-600/40 bg-amber-500/10 px-3 py-2 text-sm"
            >
              Contributor mode: Meta may use the content you send to train future models.
            </p>
          ) : null}
          <div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowBundle((value) => !value)}
            >
              {showBundle ? "Hide evidence bundle" : "Show evidence bundle"}
            </Button>
            {showBundle ? (
              <pre
                data-testid="disclosure-bundle"
                className="mt-2 max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs"
              >
                {JSON.stringify(preview.bundle, null, 2)}
              </pre>
            ) : null}
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={onCancel}>
              Cancel
            </Button>
            <Button size="sm" disabled={busy} onClick={onConfirm}>
              {busy ? "Investigating…" : "Confirm and investigate"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

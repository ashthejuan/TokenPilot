"use client";

import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { components } from "@/lib/api-types";
import { evidenceHref } from "@/lib/insights";
import { latestInvestigation } from "@/lib/investigate";

type InvestigationOut = components["schemas"]["InvestigationOut"];
type ResolvedEvidence = components["schemas"]["ResolvedEvidence"];

type InvestigationPanelProps = {
  investigations: InvestigationOut[];
  evidenceRows: ResolvedEvidence[];
};

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function facts(value: unknown): { statement: string; evidence_ids: string[] }[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "object" || item === null) return [];
    const record = item as Record<string, unknown>;
    if (typeof record["statement"] !== "string") return [];
    return [
      {
        statement: record["statement"] as string,
        evidence_ids: strings(record["evidence_ids"]),
      },
    ];
  });
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <h3 className="text-sm font-medium">{title}</h3>
      <div className="text-sm text-muted-foreground">{children}</div>
    </div>
  );
}

export function InvestigationPanel({ investigations, evidenceRows }: InvestigationPanelProps) {
  const latest = latestInvestigation(investigations);

  if (latest === null) {
    return <p className="text-sm">Not yet investigated</p>;
  }

  if (latest.status === "failed") {
    return (
      <div data-testid="investigation-failed" role="alert" className="space-y-2">
        <p className="text-sm">Investigation failed. No finding was recorded.</p>
        {strings(latest.validation_errors).map((message) => (
          <p key={message} className="text-sm text-destructive">
            {message}
          </p>
        ))}
      </div>
    );
  }

  const result = (latest.result ?? {}) as Record<string, unknown>;
  const limitations = strings(result["limitations"]);
  const validationErrors = strings(latest.validation_errors);

  if (latest.status === "insufficient_evidence") {
    return (
      <div data-testid="investigation-insufficient" className="space-y-2">
        <p className="text-sm">
          Not enough evidence to support a finding. Nothing was recorded as a
          recommendation.
        </p>
        {validationErrors.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {validationErrors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        ) : null}
        {limitations.length > 0 ? (
          <Section title="Limitations">
            <ul className="list-disc space-y-1 pl-5">
              {limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </Section>
        ) : null}
      </div>
    );
  }

  const observedFacts = facts(result["observed_facts"]);
  const recommendation = (result["recommendation"] ?? {}) as Record<string, unknown>;
  const benchmark = (recommendation["proposed_benchmark"] ?? null) as Record<string, unknown> | null;
  const rowsById = new Map(evidenceRows.map((row) => [row.ref.id, row]));

  return (
    <div data-testid="investigation-panel" className="space-y-4">
      <Section title="Observed facts">
        {observedFacts.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5">
            {observedFacts.map((fact, index) => (
              <li key={`${index}:${fact.statement}`}>
                {fact.statement}{" "}
                {fact.evidence_ids.map((id) => {
                  const row = rowsById.get(id);
                  const href =
                    row !== undefined ? evidenceHref(row.ref, row) : null;
                  return href !== null ? (
                    <Link
                      key={id}
                      href={href}
                      className="underline underline-offset-4"
                      title={id}
                    >
                      [evidence]
                    </Link>
                  ) : (
                    <span key={id} title={id} className="text-muted-foreground">
                      [evidence]
                    </span>
                  );
                })}
              </li>
            ))}
          </ul>
        ) : (
          <p>No observed facts.</p>
        )}
      </Section>
      <Section title="Hypothesis">
        <p className="whitespace-pre-wrap">{text(result["root_cause_hypothesis"])}</p>
      </Section>
      <Section title="Proposed experiment">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt>Action</dt>
          <dd>{text(recommendation["action"])}</dd>
          <dt>Change</dt>
          <dd>{text(recommendation["variable_to_change"])}</dd>
          <dt>Expect</dt>
          <dd>{text(recommendation["expected_direction"])}</dd>
        </dl>
        <p className="mt-2 whitespace-pre-wrap">
          {text(recommendation["validation_procedure"])}
        </p>
        {benchmark !== null ? (
          <p className="mt-1">
            Benchmark: {text(benchmark["baseline_change"])} vs{" "}
            {text(benchmark["alternative_change"])}
          </p>
        ) : null}
      </Section>
      {limitations.length > 0 ? (
        <Section title="Limitations">
          <ul className="list-disc space-y-1 pl-5">
            {limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

export function InvestigationCard({
  investigations,
  evidenceRows,
}: InvestigationPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Investigation</CardTitle>
      </CardHeader>
      <CardContent>
        <InvestigationPanel investigations={investigations} evidenceRows={evidenceRows} />
      </CardContent>
    </Card>
  );
}

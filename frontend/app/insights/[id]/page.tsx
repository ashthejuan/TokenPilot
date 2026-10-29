"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { EvidenceTable } from "@/components/EvidenceTable";
import { InsightActions } from "@/components/InsightActions";
import { MeasurementsTable } from "@/components/MeasurementsTable";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiGet } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { impactLabel, ruleLabel } from "@/lib/insights";

type InsightDetail = components["schemas"]["InsightDetail"];
type InsightOut = components["schemas"]["InsightOut"];

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "proxy_not_configured") {
      return "The web server has no local token. Start it with `make dev-web`.";
    }
    if (error.code === "upstream_unreachable" || error.code === "upstream_timeout") {
      return "The TokenPilot API is not answering. Start it with `make dev-api`.";
    }
    if (error.status === 404) return "Insight not found.";
    return `${error.message} (${error.code})`;
  }
  return "Could not reach the TokenPilot web server.";
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export default function InsightDetailPage() {
  const params = useParams<{ id: string }>();
  const insightId = params.id;

  const [detail, setDetail] = useState<InsightDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiGet<InsightDetail>(`api/v1/insights/${insightId}`)
      .then((next) => {
        if (cancelled) return;
        setDetail(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [insightId]);

  function onUpdated(insight: InsightOut) {
    setDetail((current) => (current ? { ...current, insight } : current));
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl">
        <p className="text-sm text-muted-foreground">Loading insight…</p>
      </div>
    );
  }

  if (error || detail === null) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Link href="/insights" className="text-sm text-muted-foreground underline-offset-4 hover:underline">
          ← Insights
        </Link>
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error ?? "Insight not found."}
        </div>
      </div>
    );
  }

  const { insight, evidence_rows: evidenceRows } = detail;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="space-y-3">
        <Link href="/insights" className="text-sm text-muted-foreground underline-offset-4 hover:underline">
          ← Insights
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{insight.title}</h1>
          <SeverityBadge severity={insight.severity} />
        </div>
        <p className="text-sm text-muted-foreground">
          {ruleLabel(insight.rule_id, insight.rule_version)}
          {insight.confidence != null ? ` · ${insight.confidence}` : null}
          {" · "}
          <span>rule heuristic</span>
        </p>
      </div>

      <Section title="Evidence">
        <EvidenceTable rows={evidenceRows} truncated={insight.evidence_truncated} />
      </Section>

      <Section title="Measurements">
        <MeasurementsTable measurements={insight.measurements} />
      </Section>

      <Section title="Impact">
        <p className="text-sm tabular-nums">
          {impactLabel(insight.estimated_impact, insight.impact_currency)}
        </p>
      </Section>

      <Section title="Rule guidance">
        <p className="text-sm whitespace-pre-wrap text-muted-foreground">
          {insight.rule_guidance ?? "No guidance available."}
        </p>
      </Section>

      <Section title="Recommended action">
        <p className="text-sm">Not yet investigated</p>
      </Section>

      <Section title="Actions">
        <InsightActions
          insightId={insight.id}
          status={insight.status}
          onUpdated={onUpdated}
        />
      </Section>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Chapter } from "@/components/Chapter";
import { DisclosureDialog } from "@/components/DisclosureDialog";
import { EvidenceTable } from "@/components/EvidenceTable";
import { FeedbackButtons } from "@/components/FeedbackButtons";
import { InsightActions } from "@/components/InsightActions";
import { InvestigationPanel } from "@/components/InvestigationPanel";
import { MeasurementsTable } from "@/components/MeasurementsTable";
import { PageHeader } from "@/components/PageHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import { ApiError, apiGet, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { impactLabel, pollJob, ruleLabel } from "@/lib/insights";
import { PAGE_SHELL } from "@/lib/layout";

type InsightDetail = components["schemas"]["InsightDetail"];
type InsightOut = components["schemas"]["InsightOut"];
type InvestigationOut = components["schemas"]["InvestigationOut"];
type InvestigationPreviewOut = components["schemas"]["InvestigationPreviewOut"];
type JobOut = components["schemas"]["JobOut"];
type Project = components["schemas"]["Project"];

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

export default function InsightDetailPage() {
  const params = useParams<{ id: string }>();
  const insightId = params.id;

  const [detail, setDetail] = useState<InsightDetail | null>(null);
  const [investigations, setInvestigations] = useState<InvestigationOut[]>([]);
  const [repositoryPath, setRepositoryPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [preview, setPreview] = useState<InvestigationPreviewOut | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      apiGet<InsightDetail>(`api/v1/insights/${insightId}`),
      apiGet<InvestigationOut[]>(`api/v1/insights/${insightId}/investigations`),
    ])
      .then(async ([next, runs]) => {
        if (cancelled) return;
        setDetail(next);
        setInvestigations(runs);
        setError(null);
        const projectId = next.insight.project_id;
        if (projectId) {
          try {
            const project = await apiGet<Project>(`api/v1/projects/${projectId}`);
            if (!cancelled) setRepositoryPath(project.repository_path);
          } catch {
            if (!cancelled) setRepositoryPath(null);
          }
        } else if (!cancelled) {
          setRepositoryPath(null);
        }
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

  async function openDisclosure() {
    setPreviewError(null);
    try {
      const next = await apiGet<InvestigationPreviewOut>(
        `api/v1/insights/${insightId}/investigation-preview`,
      );
      setPreview(next);
    } catch (err: unknown) {
      // A preview failure must not wipe the loaded insight; it stays scoped
      // to the investigation action.
      setPreviewError(errorText(err));
    }
  }

  async function confirmInvestigate() {
    if (dialogBusy) return;
    setDialogBusy(true);
    setDialogError(null);
    try {
      const accepted = await apiSend<{ job_id: string }>(
        "POST",
        `api/v1/insights/${insightId}/investigate`,
        { mode: "metadata_only" },
      );
      // Match the e2e budget: the job may outlive the default 60s poll.
      const job: JobOut = await pollJob(accepted.job_id, {
        intervalMs: 1000,
        timeoutMs: 90000,
      });
      if (job.status !== "succeeded") {
        throw new ApiError("job_failed", job.error ?? "Investigation job failed.", 500);
      }
      const [next, runs] = await Promise.all([
        apiGet<InsightDetail>(`api/v1/insights/${insightId}`),
        apiGet<InvestigationOut[]>(`api/v1/insights/${insightId}/investigations`),
      ]);
      setDetail(next);
      setInvestigations(runs);
      setPreview(null);
    } catch (err: unknown) {
      setDialogError(errorText(err));
    } finally {
      setDialogBusy(false);
    }
  }

  if (loading) {
    return (
      <div className={PAGE_SHELL}>
        <p className="text-sm text-muted-foreground">Loading insight…</p>
      </div>
    );
  }

  if (error || detail === null) {
    return (
      <div className={PAGE_SHELL}>
        <Link href="/insights" className="text-sm text-muted-foreground underline-offset-4 hover:underline">
          Insights
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
  const summaryLine = `${ruleLabel(insight.rule_id, insight.rule_version)}${insight.confidence != null ? ` · ${insight.confidence}` : ""} · rule heuristic`;

  return (
    <div className={PAGE_SHELL}>
      <p className="text-sm text-muted-foreground">
        <Link href="/insights" className="underline-offset-4 hover:underline">
          Insights
        </Link>
      </p>

      <PageHeader
        title={insight.title}
        description={summaryLine}
        actions={<SeverityBadge severity={insight.severity} />}
      />

      <Chapter title="Evidence">
        <EvidenceTable rows={evidenceRows} truncated={insight.evidence_truncated} />
      </Chapter>

      <Chapter title="Measurements">
        <MeasurementsTable measurements={insight.measurements} />
      </Chapter>

      <Chapter title="Impact">
        <p className="text-sm tabular-nums">
          {impactLabel(insight.estimated_impact, insight.impact_currency)}
        </p>
      </Chapter>

      <Chapter title="Rule guidance">
        <p className="text-sm whitespace-pre-wrap text-muted-foreground">
          {insight.rule_guidance ?? "No guidance available."}
        </p>
      </Chapter>

      <Chapter title="Investigation">
        <InvestigationPanel investigations={investigations} evidenceRows={evidenceRows} />
      </Chapter>

      <Chapter title="Feedback">
        <FeedbackButtons insightId={insight.id} />
      </Chapter>

      <Chapter title="Actions">
        {previewError ? (
          <p role="alert" className="mb-3 text-sm text-destructive">
            {previewError}
          </p>
        ) : null}
        <InsightActions
          insightId={insight.id}
          status={insight.status}
          repositoryPath={repositoryPath}
          onUpdated={onUpdated}
          onInvestigate={() => void openDisclosure()}
        />
      </Chapter>

      {preview ? (
        <DisclosureDialog
          preview={preview}
          busy={dialogBusy}
          error={dialogError}
          onConfirm={() => void confirmInvestigate()}
          onCancel={() => {
            if (!dialogBusy) setPreview(null);
          }}
        />
      ) : null}
    </div>
  );
}

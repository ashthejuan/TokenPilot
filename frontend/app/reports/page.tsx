"use client";

import { useEffect, useState, type ReactNode } from "react";

import { BasisBadge } from "@/components/BasisBadge";
import { CostValue } from "@/components/CostValue";
import { CoverageBanner } from "@/components/CoverageBanner";
import { SavingsBadge } from "@/components/SavingsBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiGet, apiGetText } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { formatCount, formatMoney } from "@/lib/format";
import { formatReportPeriod, type ProjectReport, type SavingsReport } from "@/lib/reports";

type Project = components["schemas"]["Project"];

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";
const LABEL_CLASS = "flex flex-col gap-1 text-xs font-medium text-muted-foreground";

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "proxy_not_configured") {
      return "The web server has no local token. Start it with `make dev-web`.";
    }
    if (error.code === "upstream_unreachable" || error.code === "upstream_timeout") {
      return "The TokenPilot API is not answering. Start it with `make dev-api`.";
    }
    return `${error.message} (${error.code})`;
  }
  return "Could not reach the TokenPilot web server.";
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium tabular-nums">{children}</p>
    </div>
  );
}

function toIsoOrEmpty(localValue: string): string | undefined {
  if (!localValue.trim()) return undefined;
  const date = new Date(localValue);
  if (Number.isNaN(date.getTime())) return undefined;
  return date.toISOString();
}

function downloadMarkdown(filename: string, markdown: string) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function ReportsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [fromLocal, setFromLocal] = useState("");
  const [toLocal, setToLocal] = useState("");
  const [report, setReport] = useState<ProjectReport | null>(null);
  const [savings, setSavings] = useState<SavingsReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<Project[]>("api/v1/projects")
      .then((list) => {
        if (cancelled) return;
        setProjects(list);
        setProjectsError(null);
        if (list.length > 0) {
          setProjectId((current) => current || list[0].id);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setProjectsError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function loadReport() {
    if (!projectId || loading) return;
    setLoading(true);
    setError(null);
    const from = toIsoOrEmpty(fromLocal);
    const to = toIsoOrEmpty(toLocal);
    const params: Record<string, string> = { format: "json" };
    if (from) params.from = from;
    if (to) params.to = to;
    const savingsParams: Record<string, string> = { project_id: projectId };
    if (from) savingsParams.from = from;
    if (to) savingsParams.to = to;
    try {
      const [nextReport, nextSavings] = await Promise.all([
        apiGet<ProjectReport>(`api/v1/reports/project/${projectId}`, params),
        apiGet<SavingsReport>("api/v1/reports/savings", savingsParams),
      ]);
      setReport(nextReport);
      setSavings(nextSavings);
    } catch (err: unknown) {
      setError(errorText(err));
      setReport(null);
      setSavings(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleDownloadMarkdown() {
    if (!projectId || downloading) return;
    setDownloading(true);
    setError(null);
    const from = toIsoOrEmpty(fromLocal);
    const to = toIsoOrEmpty(toLocal);
    const params: Record<string, string> = { format: "markdown" };
    if (from) params.from = from;
    if (to) params.to = to;
    try {
      const markdown = await apiGetText(`api/v1/reports/project/${projectId}`, params);
      const project = projects.find((p) => p.id === projectId);
      const slug = project?.slug ?? projectId.slice(0, 8);
      downloadMarkdown(`${slug}-report.md`, markdown);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setDownloading(false);
    }
  }

  const currency = report?.currency ?? null;
  const savingsStrip = savings ?? report?.savings ?? null;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">Reports</h1>
          <p className="text-sm text-muted-foreground">
            Project spend, waste, recommendations, and savings kinds — never summed.
          </p>
        </div>
      </div>

      {projectsError ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {projectsError}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Report filters</CardTitle>
          <CardDescription>Optional from/to are inclusive start and exclusive end (UTC).</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label className={LABEL_CLASS}>
              Project
              <select
                className={SELECT_CLASS}
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                disabled={projects.length === 0}
              >
                {projects.length === 0 ? <option value="">No projects</option> : null}
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label className={LABEL_CLASS}>
              From (local)
              <Input
                type="datetime-local"
                value={fromLocal}
                onChange={(e) => setFromLocal(e.target.value)}
              />
            </label>
            <label className={LABEL_CLASS}>
              To (local)
              <Input
                type="datetime-local"
                value={toLocal}
                onChange={(e) => setToLocal(e.target.value)}
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              className="pressable"
              size="sm"
              onClick={() => void loadReport()}
              disabled={!projectId || loading}
            >
              {loading ? "Loading…" : "Load report"}
            </Button>
            <Button
              className="pressable"
              size="sm"
              variant="outline"
              onClick={() => void handleDownloadMarkdown()}
              disabled={!projectId || downloading}
            >
              {downloading ? "Downloading…" : "Download Markdown"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}

      {report === null && !loading && !error ? (
        <p className="text-sm text-muted-foreground">Select a project and load a report.</p>
      ) : null}

      {report ? (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{report.project_name}</CardTitle>
              <CardDescription>Period: {formatReportPeriod(report.period)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <CostValue
                  value={report.spend_total}
                  currency={currency}
                  className="text-3xl font-semibold"
                />
                <BasisBadge basis={report.cost_basis} />
              </div>
              <CoverageBanner
                coverage={report.coverage}
                eventsWithUnknownCost={report.unknown_cost_events}
              />
              {report.unattributed.events > 0 ? (
                <p className="text-xs text-muted-foreground">
                  Unattributed in window: {formatCount(report.unattributed.events)} events ·{" "}
                  {formatMoney(report.unattributed.estimated_cost, currency)}
                </p>
              ) : null}
            </CardContent>
          </Card>

          {savingsStrip ? (
            <Card>
              <CardHeader>
                <CardTitle>Savings kinds</CardTitle>
                <CardDescription>
                  Potential, benchmark, verified, and realized are shown separately and never added.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Stat label="Potential">
                    <CostValue value={savingsStrip.potential} currency={currency} />
                  </Stat>
                  <Stat label="Benchmark">
                    <CostValue value={savingsStrip.benchmark} currency={currency} />
                  </Stat>
                  <Stat label="Verified">
                    <CostValue value={savingsStrip.verified} currency={currency} />
                  </Stat>
                  <Stat label="Realized">
                    <CostValue value={savingsStrip.realized ?? null} currency={currency} />
                  </Stat>
                </div>
              </CardContent>
            </Card>
          ) : null}

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Cost by outcome</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                  <Stat label="Passed">
                    <CostValue value={report.cost_by_outcome.passed} currency={currency} />
                  </Stat>
                  <Stat label="Failed">
                    <CostValue value={report.cost_by_outcome.failed} currency={currency} />
                  </Stat>
                  <Stat label="Unknown">
                    <CostValue value={report.cost_by_outcome.unknown} currency={currency} />
                  </Stat>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Waste by rule</CardTitle>
              </CardHeader>
              <CardContent>
                {report.waste_by_rule.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No non-dismissed waste in this period.</p>
                ) : (
                  <ul className="space-y-2">
                    {report.waste_by_rule.map((row) => (
                      <li key={row.rule_id} className="flex items-baseline justify-between gap-3 text-sm">
                        <span className="font-mono text-xs">{row.rule_id}</span>
                        <span className="tabular-nums text-muted-foreground">
                          {formatCount(row.count)} · {formatMoney(row.estimated_impact, currency)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Top sessions</CardTitle>
            </CardHeader>
            <CardContent>
              {report.top_sessions.length === 0 ? (
                <p className="text-sm text-muted-foreground">No sessions in this period.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Session</TableHead>
                      <TableHead>Outcome</TableHead>
                      <TableHead>Requests</TableHead>
                      <TableHead>Cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {report.top_sessions.map((session) => (
                      <TableRow key={session.session_id}>
                        <TableCell className="font-mono text-xs">
                          {session.session_id.slice(0, 8)}
                        </TableCell>
                        <TableCell>{session.outcome}</TableCell>
                        <TableCell className="tabular-nums">{formatCount(session.request_count)}</TableCell>
                        <TableCell className="tabular-nums">
                          {formatMoney(session.estimated_cost, session.currency)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recommendations</CardTitle>
            </CardHeader>
            <CardContent>
              {report.top_recommendations.length === 0 ? (
                <p className="text-sm text-muted-foreground">No investigated recommendations yet.</p>
              ) : (
                <ul className="space-y-3">
                  {report.top_recommendations.map((rec) => (
                    <li key={rec.insight_id} className="space-y-1">
                      <p className="text-sm font-medium">{rec.title}</p>
                      <p className="text-xs text-muted-foreground">
                        <span className="font-mono">{rec.rule_id}</span>
                        {" · "}
                        {formatMoney(rec.estimated_impact, rec.impact_currency)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Benchmarks</CardTitle>
            </CardHeader>
            <CardContent>
              {report.benchmarks.length === 0 ? (
                <p className="text-sm text-muted-foreground">No comparisons for this project yet.</p>
              ) : (
                <ul className="space-y-3">
                  {report.benchmarks.map((bench, index) => (
                    <li key={`${bench.name}-${index}`} className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{bench.name}</span>
                        <SavingsBadge
                          status={bench.comparison_status}
                          correctness_preserved={null}
                          cost_delta={bench.cost_delta}
                        />
                        <span className="text-xs text-muted-foreground tabular-nums">
                          Δ {formatMoney(bench.cost_delta, currency)}
                          {bench.cost_delta_pct != null ? ` (${bench.cost_delta_pct}%)` : null}
                        </span>
                      </div>
                      <details className="text-xs">
                        <summary className="cursor-pointer text-muted-foreground">
                          Methodology
                        </summary>
                        <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-muted p-2 font-mono">
                          {JSON.stringify(bench.methodology, null, 2)}
                        </pre>
                      </details>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Limitations</CardTitle>
            </CardHeader>
            <CardContent>
              {report.limitations.length === 0 ? (
                <p className="text-sm text-muted-foreground">No limitations listed.</p>
              ) : (
                <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {report.limitations.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
}

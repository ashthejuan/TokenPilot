"use client";

import { useCallback, useEffect, useState } from "react";

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
import { ApiError, apiGet, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/format";

type Project = components["schemas"]["Project"];
type ProjectCreate = components["schemas"]["ProjectCreate"];

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

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [repositoryPath, setRepositoryPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    return apiGet<Project[]>("api/v1/projects")
      .then((list) => {
        setProjects(list);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(errorText(err));
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createProject() {
    if (busy) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setFormError("Name is required.");
      return;
    }
    setBusy(true);
    setFormError(null);
    const body: ProjectCreate = {
      name: trimmed,
      default_currency: "USD",
      repository_path: repositoryPath.trim() || null,
    };
    try {
      await apiSend<Project>("POST", "api/v1/projects", body);
      setName("");
      setRepositoryPath("");
      await refresh();
    } catch (err: unknown) {
      setFormError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <p className="text-sm text-muted-foreground">
          Register repositories so usage can be attributed and benchmarks can run.
        </p>
      </div>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>New project</CardTitle>
          <CardDescription>Name is required; repository path enables benchmarking.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {formError ? (
            <div
              role="alert"
              className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
            >
              {formError}
            </div>
          ) : null}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className={LABEL_CLASS}>
              Name
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Invoicing demo"
              />
            </label>
            <label className={LABEL_CLASS}>
              Repository path
              <Input
                value={repositoryPath}
                onChange={(e) => setRepositoryPath(e.target.value)}
                placeholder="/path/to/repo"
              />
            </label>
          </div>
          <Button className="pressable" size="sm" onClick={() => void createProject()} disabled={busy}>
            {busy ? "Creating…" : "Create project"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Projects</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading projects…</p>
          ) : projects.length === 0 ? (
            <p className="text-sm text-muted-foreground">No projects yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Repository</TableHead>
                  <TableHead>Currency</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {projects.map((project) => (
                  <TableRow key={project.id}>
                    <TableCell className="font-medium">{project.name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {project.slug ?? "—"}
                    </TableCell>
                    <TableCell className="max-w-xs truncate font-mono text-xs" title={project.repository_path ?? undefined}>
                      {project.repository_path ?? "—"}
                    </TableCell>
                    <TableCell className="tabular-nums">{project.default_currency}</TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">
                      {formatTimestamp(project.updated_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

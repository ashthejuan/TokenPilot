"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Chapter } from "@/components/Chapter";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiDelete, apiGet, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/format";
import { PAGE_SHELL } from "@/lib/layout";

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
  const [deletingId, setDeletingId] = useState<string | null>(null);
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
    if (busy || deletingId !== null) return;
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

  function confirmDeleteProject(project: Project) {
    if (busy || deletingId !== null) return;
    toast(`Delete “${project.name}”?`, {
      id: `delete-project-${project.id}`,
      description:
        "Linked benchmarks and tasks are removed; sessions and usage stay as unattributed.",
      duration: Infinity,
      action: {
        label: "Delete",
        onClick: () => {
          void performDelete(project);
        },
      },
      cancel: {
        label: "Cancel",
        onClick: () => toast.dismiss(`delete-project-${project.id}`),
      },
    });
  }

  async function performDelete(project: Project) {
    if (busy || deletingId !== null) return;
    toast.dismiss(`delete-project-${project.id}`);
    setDeletingId(project.id);
    setError(null);
    const loadingId = toast.loading(`Deleting “${project.name}”…`);
    try {
      await apiDelete<null>(`api/v1/projects/${project.id}`);
      await refresh();
      toast.success(`Deleted “${project.name}”`, { id: loadingId });
    } catch (err: unknown) {
      const message = errorText(err);
      setError(message);
      toast.error(message, { id: loadingId });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className={PAGE_SHELL}>
      <PageHeader
        title="Projects"
        description="Register repositories so usage can be attributed and benchmarks can run."
      />

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}

      <Chapter
        title="New project"
        description="Name is required; repository path enables benchmarking."
      >
        <div className="space-y-4">
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
        </div>
      </Chapter>

      <Chapter title="Projects">
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
                <TableHead className="w-[1%] text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
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
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      className="pressable"
                      disabled={busy || deletingId !== null}
                      aria-label={`Delete project ${project.name}`}
                      onClick={() => confirmDeleteProject(project)}
                    >
                      {deletingId === project.id ? "Deleting…" : "Delete"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Chapter>
    </div>
  );
}

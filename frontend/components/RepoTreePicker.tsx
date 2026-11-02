"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, apiGet } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { addContextPath, removeContextPath } from "@/lib/benchmarks";

type ProjectTree = components["schemas"]["ProjectTree"];
type TreeEntry = components["schemas"]["TreeEntry"];

const LABEL_CLASS = "flex flex-col gap-1 text-xs font-medium text-muted-foreground";

function treeErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.message} (${error.code})`;
  }
  return "Could not load repository tree.";
}

function joinPrefix(repositoryPath: string, relative: string): string {
  const base = repositoryPath.replace(/\/+$/, "");
  if (!relative) return base || "/";
  return `${base}/${relative}`;
}

export type RepoTreePickerProps = {
  projectId: string;
  repositoryPath: string;
  selectedPaths: string[];
  onSelectedPathsChange: (paths: string[]) => void;
};

export function RepoTreePicker({
  projectId,
  repositoryPath,
  selectedPaths,
  onSelectedPathsChange,
}: RepoTreePickerProps) {
  const [open, setOpen] = useState(false);
  const [browsePath, setBrowsePath] = useState("");
  const [entries, setEntries] = useState<TreeEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTree = useCallback(
    async (path: string) => {
      if (!projectId) return;
      setLoading(true);
      setError(null);
      try {
        const tree = await apiGet<ProjectTree>(
          `api/v1/projects/${encodeURIComponent(projectId)}/tree`,
          path ? { path } : undefined,
        );
        setBrowsePath(tree.path);
        setEntries(tree.entries);
      } catch (err: unknown) {
        setError(treeErrorText(err));
        setEntries([]);
      } finally {
        setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    if (!open) return;
    void loadTree("");
  }, [open, loadTree]);

  function selectEntry(entry: TreeEntry) {
    onSelectedPathsChange(addContextPath(selectedPaths, entry.path));
  }

  function removeChip(path: string) {
    onSelectedPathsChange(removeContextPath(selectedPaths, path));
  }

  function enterDir(entry: TreeEntry) {
    if (entry.kind !== "dir") return;
    void loadTree(entry.path);
  }

  function goUp() {
    if (!browsePath) return;
    const parent = browsePath.includes("/")
      ? browsePath.slice(0, browsePath.lastIndexOf("/"))
      : "";
    void loadTree(parent);
  }

  const lockedPrefix = joinPrefix(repositoryPath, "");

  return (
    <div className={`${LABEL_CLASS} sm:col-span-2`}>
      Context paths
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-input bg-muted/40 px-2.5 py-2 text-sm text-foreground">
        <span
          className="max-w-[min(100%,18rem)] truncate rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground"
          title={lockedPrefix}
        >
          {lockedPrefix || "(no repository path)"}
        </span>
        {selectedPaths.map((path) => (
          <button
            key={path}
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-2 py-0.5 font-mono text-xs hover:bg-accent"
            onClick={() => removeChip(path)}
            title="Remove path"
          >
            {path}
            <span aria-hidden className="text-muted-foreground">
              ×
            </span>
          </button>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto h-7"
          onClick={() => setOpen((current) => !current)}
          disabled={!projectId}
        >
          {open ? "Hide browse" : "Browse"}
        </Button>
      </div>
      {open ? (
        <div className="rounded-lg border border-input bg-transparent p-2 text-sm">
          <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
            <button
              type="button"
              className="underline disabled:no-underline disabled:opacity-40"
              onClick={goUp}
              disabled={!browsePath || loading}
            >
              Up
            </button>
            <span className="font-mono truncate">
              {joinPrefix(repositoryPath, browsePath)}
            </span>
          </div>
          {error ? (
            <p className="text-xs text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          {loading ? <p className="text-xs text-muted-foreground">Loading…</p> : null}
          {!loading && !error && entries.length === 0 ? (
            <p className="text-xs text-muted-foreground">Empty folder.</p>
          ) : null}
          <ul className="max-h-48 space-y-0.5 overflow-y-auto">
            {entries.map((entry) => (
              <li key={entry.path} className="flex items-center gap-2">
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate rounded px-1.5 py-1 text-left font-mono text-xs hover:bg-accent"
                  onClick={() =>
                    entry.kind === "dir" ? enterDir(entry) : selectEntry(entry)
                  }
                  onDoubleClick={() => selectEntry(entry)}
                >
                  <span className="mr-1 text-muted-foreground">
                    {entry.kind === "dir" ? "[dir]" : "[file]"}
                  </span>
                  {entry.name}
                </button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 shrink-0 px-2 text-xs"
                  onClick={() => selectEntry(entry)}
                >
                  Add
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

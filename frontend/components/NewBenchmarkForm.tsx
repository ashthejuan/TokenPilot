"use client";

import { useEffect, useState } from "react";

import { RepoTreePicker } from "@/components/RepoTreePicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiGet, apiSend } from "@/lib/api";
import type { components } from "@/lib/api-types";
import {
  allowOutsideHelperText,
  buildAcceptanceConfig,
  buildAlternativeSpec,
  type AcceptanceMode,
  type ContextStrategy,
  type Project,
} from "@/lib/benchmarks";

type BenchmarkCreate = components["schemas"]["BenchmarkCreate"];
type BenchmarkOut = components["schemas"]["BenchmarkOut"];

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";
const TEXTAREA_CLASS =
  "min-h-24 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";
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

export function NewBenchmarkForm({ onCreated }: { onCreated: (benchmarkId: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [repositoryPath, setRepositoryPath] = useState("");
  const [taskPrompt, setTaskPrompt] = useState("");
  const [modelId, setModelId] = useState("");
  const [maxSteps, setMaxSteps] = useState("12");
  const [altName, setAltName] = useState("targeted-context");
  const [altStrategy, setAltStrategy] = useState<ContextStrategy>("targeted");
  const [altModel, setAltModel] = useState("");
  const [contextFiles, setContextFiles] = useState<string[]>([]);
  const [allowOutside, setAllowOutside] = useState(false);
  const [acceptanceMode, setAcceptanceMode] = useState<AcceptanceMode>("command");
  const [acceptanceCommand, setAcceptanceCommand] = useState("");
  const [requiredPass, setRequiredPass] = useState("");
  const [minSuccessRate, setMinSuccessRate] = useState("1");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiGet<Project[]>("api/v1/projects")
      .then((list) => {
        if (cancelled) return;
        setProjects(list);
        if (list.length > 0) {
          setProjectId((current) => current || list[0].id);
          setRepositoryPath((current) => current || list[0].repository_path || "");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function selectProject(id: string) {
    setProjectId(id);
    const project = projects.find((candidate) => candidate.id === id);
    if (project) setRepositoryPath(project.repository_path || "");
    setContextFiles([]);
  }

  async function submit() {
    if (busy) return;
    const steps = Number.parseInt(maxSteps, 10);
    if (!Number.isInteger(steps) || steps < 1) {
      setError("Max steps must be a positive integer.");
      return;
    }

    const acceptance = buildAcceptanceConfig({
      mode: acceptanceMode,
      commandText: acceptanceCommand,
      requiredPassText: requiredPass,
      minSuccessRateText: minSuccessRate,
    });
    if ("error" in acceptance) {
      setError(acceptance.error);
      return;
    }

    const alternative = buildAlternativeSpec({
      name: altName,
      strategy: altStrategy,
      modelId: altModel,
      allowOutside,
      contextFiles,
    });
    if ("error" in alternative) {
      setError(alternative.error);
      return;
    }

    setBusy(true);
    setError(null);
    const body: BenchmarkCreate = {
      project_id: projectId,
      repository_path: repositoryPath,
      name,
      task_prompt: taskPrompt,
      initial_ref: "main",
      repeat_count: 1,
      timeout_s: 300,
      acceptance,
      baseline: {
        model_id: modelId,
        max_steps: steps,
        context_strategy: "full_repo",
        allow_outside_paths: false,
        prompt_template: "fix_v1",
      },
      alternatives: [alternative],
    };
    try {
      const created = await apiSend<BenchmarkOut>("POST", "api/v1/benchmarks", body);
      onCreated(created.id);
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const commandMode = acceptanceMode === "command";
  const targeted = altStrategy === "targeted";

  return (
    <div className="space-y-4">
      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className={LABEL_CLASS}>
          Project
          <select
            className={SELECT_CLASS}
            value={projectId}
            onChange={(e) => selectProject(e.target.value)}
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label className={LABEL_CLASS}>
          Name
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="fix-discount-before-tax"
          />
        </label>
        <label className={`${LABEL_CLASS} sm:col-span-2`}>
          Repository path
          <Input
            value={repositoryPath}
            onChange={(e) => setRepositoryPath(e.target.value)}
            placeholder="/path/to/repo"
          />
        </label>
        <label className={`${LABEL_CLASS} sm:col-span-2`}>
          Task prompt
          <textarea
            className={TEXTAREA_CLASS}
            value={taskPrompt}
            onChange={(e) => setTaskPrompt(e.target.value)}
            placeholder="Describe the bug to fix. Do not change any tests."
          />
        </label>
        <label className={LABEL_CLASS}>
          Baseline model
          <Input
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            placeholder="muse-spark-1.3"
          />
        </label>
        <label className={LABEL_CLASS}>
          Baseline max steps
          <Input
            value={maxSteps}
            inputMode="numeric"
            onChange={(e) => setMaxSteps(e.target.value)}
          />
        </label>
        <label className={LABEL_CLASS}>
          Alternative name
          <Input value={altName} onChange={(e) => setAltName(e.target.value)} />
        </label>
        <label className={LABEL_CLASS}>
          Alternative context strategy
          <select
            className={SELECT_CLASS}
            value={altStrategy}
            onChange={(e) => setAltStrategy(e.target.value as ContextStrategy)}
          >
            <option value="targeted">targeted</option>
            <option value="full_repo">full_repo</option>
          </select>
        </label>
        <label className={LABEL_CLASS}>
          Alternative model
          <Input
            value={altModel}
            onChange={(e) => setAltModel(e.target.value)}
            placeholder="Leave blank to inherit baseline"
          />
        </label>
        {targeted ? (
          <>
            <RepoTreePicker
              projectId={projectId}
              repositoryPath={repositoryPath}
              selectedPaths={contextFiles}
              onSelectedPathsChange={setContextFiles}
            />
            <label className={`${LABEL_CLASS} sm:col-span-2 gap-2`}>
              <span className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="size-4 rounded border border-input"
                  checked={allowOutside}
                  onChange={(e) => setAllowOutside(e.target.checked)}
                />
                Allow outside path access
              </span>
              <span className="font-normal text-muted-foreground">
                {allowOutsideHelperText(allowOutside)}
              </span>
            </label>
          </>
        ) : null}
        <label className={`${LABEL_CLASS} sm:col-span-2`}>
          Acceptance mode
          <select
            className={SELECT_CLASS}
            value={acceptanceMode}
            onChange={(e) => setAcceptanceMode(e.target.value as AcceptanceMode)}
          >
            <option value="command">Acceptance tests</option>
            <option value="metrics_only">Metrics only</option>
          </select>
        </label>
        {commandMode ? (
          <>
            <label className={`${LABEL_CLASS} sm:col-span-2`}>
              Acceptance command
              <Input
                value={acceptanceCommand}
                onChange={(e) => setAcceptanceCommand(e.target.value)}
                placeholder="python -m pytest -q"
                required
              />
            </label>
            <label className={`${LABEL_CLASS} sm:col-span-2`}>
              Required pass (one pytest nodeid per line, optional)
              <textarea
                className={TEXTAREA_CLASS}
                value={requiredPass}
                onChange={(e) => setRequiredPass(e.target.value)}
                placeholder={"tests/test_discounts.py::test_applies_before_tax"}
              />
            </label>
            <label className={LABEL_CLASS}>
              Min success rate
              <Input
                value={minSuccessRate}
                inputMode="decimal"
                onChange={(e) => setMinSuccessRate(e.target.value)}
                placeholder="1"
              />
            </label>
          </>
        ) : null}
      </div>
      <Button className="pressable" size="sm" onClick={() => void submit()} disabled={busy}>
        {busy ? "Creating…" : "Create benchmark"}
      </Button>
    </div>
  );
}

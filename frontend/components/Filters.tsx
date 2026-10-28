"use client";

import type { ReactNode } from "react";

import { Input } from "@/components/ui/input";
import type { components } from "@/lib/api-types";
import type { OutcomeFilter, OverviewFilters, RangePreset } from "@/lib/filters";

type Project = components["schemas"]["Project"];

const RANGES: { value: RangePreset; label: string }[] = [
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "custom", label: "Custom" },
];

const OUTCOMES: { value: OutcomeFilter; label: string }[] = [
  { value: "", label: "All outcomes" },
  { value: "passed", label: "Passed" },
  { value: "failed", label: "Failed" },
  { value: "unknown", label: "Unverified" },
];

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

type FiltersProps = {
  value: OverviewFilters;
  onChange: (next: OverviewFilters) => void;
  projects: Project[];
  providers: string[];
  models: string[];
  rangeError: string | null;
};

export function Filters({ value, onChange, projects, providers, models, rangeError }: FiltersProps) {
  const set = <K extends keyof OverviewFilters>(key: K, next: OverviewFilters[K]) =>
    onChange({ ...value, [key]: next });

  return (
    <div className="flex flex-wrap items-end gap-3">
      <Field label="Date range">
        <select
          className={SELECT_CLASS}
          value={value.range}
          onChange={(e) => set("range", e.target.value as RangePreset)}
        >
          {RANGES.map((range) => (
            <option key={range.value} value={range.value}>
              {range.label}
            </option>
          ))}
        </select>
      </Field>
      {value.range === "custom" ? (
        <>
          <Field label="From">
            <Input
              type="datetime-local"
              value={value.customFrom}
              onChange={(e) => set("customFrom", e.target.value)}
            />
          </Field>
          <Field label="To">
            <Input
              type="datetime-local"
              value={value.customTo}
              onChange={(e) => set("customTo", e.target.value)}
            />
          </Field>
        </>
      ) : null}
      <Field label="Project">
        <select
          className={SELECT_CLASS}
          value={value.projectId}
          onChange={(e) => set("projectId", e.target.value)}
        >
          <option value="">All projects</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Provider">
        <select
          className={SELECT_CLASS}
          value={value.provider}
          onChange={(e) => set("provider", e.target.value)}
        >
          <option value="">All providers</option>
          {providers.map((provider) => (
            <option key={provider} value={provider}>
              {provider}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Model">
        <select
          className={SELECT_CLASS}
          value={value.modelId}
          onChange={(e) => set("modelId", e.target.value)}
        >
          <option value="">All models</option>
          {models.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Outcome">
        <select
          className={SELECT_CLASS}
          value={value.outcome}
          onChange={(e) => set("outcome", e.target.value as OutcomeFilter)}
        >
          {OUTCOMES.map((outcome) => (
            <option key={outcome.value} value={outcome.value}>
              {outcome.label}
            </option>
          ))}
        </select>
      </Field>
      {rangeError ? <p className="pb-1.5 text-sm text-destructive">{rangeError}</p> : null}
    </div>
  );
}

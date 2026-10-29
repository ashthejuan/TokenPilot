import { expect, test } from "@playwright/test";

const RUN_BASE = {
  id: "run-base",
  benchmark_id: "bench-1",
  variant_name: "baseline",
  model_id: "fake-large",
  config: { model_id: "fake-large", context_strategy: "full_repo", max_steps: 12 },
  run_status: "completed",
  outcome: "passed",
  total_cost: 0.3,
  currency: "USD",
  unknown_cost_events: 0,
  total_tokens: 100,
  request_count: 4,
  retry_count: 0,
  duration_ms: 1000,
  test_exit_code: 0,
  test_results: null,
  patch_path: "/tmp/run-base.patch",
  worktree_path: null,
  started_at: null,
  completed_at: "2026-10-28T00:00:01Z",
  repeat_index: 0,
  error: null,
  eligible: true,
};

const RUN_ALT = {
  ...RUN_BASE,
  id: "run-alt",
  variant_name: "targeted-context",
  config: { model_id: "fake-large", context_strategy: "targeted", max_steps: 12 },
  total_cost: 0.12,
};

const DETAIL = {
  id: "bench-1",
  project_id: "p1",
  task_id: "t1",
  name: "discount bug",
  description: null,
  initial_git_sha: "abc123",
  acceptance: { command: ["python", "-m", "pytest", "-q"], required_pass: [], min_success_rate: 1 },
  baseline: {
    model_id: "fake-large",
    context_strategy: "full_repo",
    max_steps: 12,
    retry_policy: { max_retries: 2 },
    temperature: null,
    prompt_template: "fix_v1",
    context_files: [],
  },
  alternatives: [{ name: "targeted-context", changes: { context_strategy: "targeted" }, context_files: [] }],
  task_prompt: "fix it",
  initial_ref: "main",
  repeat_count: 1,
  timeout_s: 300,
  created_at: "2026-10-28T00:00:00Z",
  runs: [RUN_BASE, RUN_ALT],
};

const COMPARISON = {
  id: "cmp-1",
  benchmark_id: "bench-1",
  baseline_variant: "baseline",
  alternative_variant: "targeted-context",
  baseline_run_id: "run-base",
  alternative_run_id: "run-alt",
  cost_delta: 0.18,
  cost_delta_pct: "60.0",
  correctness_preserved: true,
  comparison_status: "verified",
  methodology: {
    repeat_counts: { baseline: 1, alternative: 1 },
    eligible_counts: { baseline: 1, alternative: 1 },
    success_rates: { baseline: 1, alternative: 1 },
    cost_stdev: { baseline: null, alternative: null },
    low_sample: true,
    variables_changed: ["context_strategy"],
    interleaved: true,
  },
  reasons: ["alternative costs strictly below baseline costs"],
  created_at: "2026-10-28T00:00:02Z",
};

test("benchmark detail shows the persisted latest comparison on a fresh visit", async ({
  page,
}) => {
  let comparePosts = 0;
  await page.route("**/api/tp/api/v1/benchmarks/bench-1/comparisons", (route) =>
    route.fulfill({ json: [COMPARISON] }),
  );
  await page.route("**/api/tp/api/v1/benchmarks/bench-1/compare", (route) => {
    comparePosts += 1;
    return route.abort();
  });
  await page.route("**/api/tp/api/v1/benchmarks/bench-1", (route) =>
    route.fulfill({ json: DETAIL }),
  );

  await page.goto("/benchmarks/bench-1");

  await expect(page.getByText("Verified savings").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Total (eligible runs)")).toBeVisible();
  expect(comparePosts).toBe(0);
});

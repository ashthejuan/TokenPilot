/**
 * Offline PRD §18 demo loop: Overview spend → retry_amplification insight →
 * investigate → benchmark → verified savings, plus fail-alt honesty path.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API = "/api/tp/api/v1";
const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Mirrors demo/benchmark_task.offline.yaml (avoid adding a yaml runtime dep). */
const OFFLINE_TASK_SPEC = {
  name: "fix-discount-before-tax",
  description:
    "Fix the discount-before-tax bug in the invoicing fixture so the full test suite passes.",
  task_prompt:
    "The invoicing fixture in this repository has one bug: apply_discount in " +
    "invoicing/discounts.py applies a percentage discount after tax instead of before. " +
    "Fix the calculation so the discount is taken before tax (percentage tax on the " +
    "discounted subtotal, flat levy added in full afterwards), making the full test " +
    "suite pass. Do not change any tests.",
  initial_ref: "main",
  acceptance: {
    command: ["python", "-m", "pytest", "-q"],
    required_pass: ["tests/test_discounts.py::test_discount_applied_before_tax"],
    min_success_rate: 1.0,
  },
  timeout_s: 300,
  repeat_count: 1,
  baseline: {
    model_id: "fake-large",
    context_strategy: "full_repo",
    max_steps: 12,
    retry_policy: { max_retries: 2 },
  },
  alternatives: [
    {
      name: "targeted-context",
      changes: { context_strategy: "targeted" },
      context_files: [
        "invoicing/discounts.py",
        "invoicing/tax.py",
        "tests/test_discounts.py",
      ],
    },
  ],
};

async function waitJob(request: APIRequestContext, jobId: string, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await request.get(`${API}/jobs/${jobId}`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    if (body.status === "succeeded") return body;
    if (body.status === "failed") {
      throw new Error(`job ${jobId} failed: ${JSON.stringify(body)}`);
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`job ${jobId} timed out`);
}

async function waitRuns(request: APIRequestContext, benchmarkId: string, timeoutMs = 300_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await request.get(`${API}/benchmarks/${benchmarkId}`);
    expect(res.ok()).toBeTruthy();
    const detail = await res.json();
    const runs = detail.runs as { run_status: string; outcome: string | null }[];
    if (
      runs.length > 0 &&
      runs.every((r) => r.run_status === "completed" || r.run_status === "failed")
    ) {
      return detail;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`benchmark ${benchmarkId} runs timed out`);
}

function initFixture(): string {
  const dest = mkdtempSync(join(tmpdir(), "tp-demo-fixture-"));
  execFileSync("bash", [join(REPO_ROOT, "demo", "scripts", "init_fixture_repo.sh"), dest], {
    stdio: "pipe",
  });
  return dest;
}

async function setFakeScenario(scenario: "success" | "fail-alt") {
  const fakeUrl = process.env.TOKENPILOT_E2E_FAKE_URL;
  expect(fakeUrl).toBeTruthy();
  // Sticky scenario via header on any request to the fake.
  await fetch(fakeUrl!, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Fake-Demo-Scenario": scenario,
    },
    body: JSON.stringify({ model: "fake-large", messages: [{ role: "user", content: "ping" }] }),
  });
}

async function ensureProject(request: APIRequestContext, repositoryPath: string) {
  const list = await request.get(`${API}/projects`);
  expect(list.ok()).toBeTruthy();
  const projects = (await list.json()) as { id: string; slug: string | null }[];
  const existing = projects.find((p) => p.slug === "invoicing-demo");
  if (existing) {
    const patched = await request.patch(`${API}/projects/${existing.id}`, {
      data: { repository_path: repositoryPath },
    });
    expect(patched.ok()).toBeTruthy();
    return existing.id;
  }
  const created = await request.post(`${API}/projects`, {
    data: {
      name: "invoicing-demo",
      slug: "invoicing-demo",
      repository_path: repositoryPath,
    },
  });
  expect(created.ok()).toBeTruthy();
  return ((await created.json()) as { id: string }).id;
}

async function seedViaGateway() {
  // Prefer the real seed script so e2e matches make demo-offline (gateway path).
  execFileSync(
    "uv",
    [
      "run",
      "--directory",
      join(REPO_ROOT, "backend"),
      "python",
      join(REPO_ROOT, "demo", "scripts", "seed_sessions.py"),
      "--mode",
      "offline",
      "--project",
      "invoicing-demo",
    ],
    {
      env: {
        ...process.env,
        TOKENPILOT_API_URL: "http://127.0.0.1:8788",
        TOKENPILOT_LOCAL_TOKEN: "e2e-local-token",
      },
      stdio: "pipe",
    },
  );
}

async function analyze(request: APIRequestContext) {
  const res = await request.post(`${API}/insights/analyze`, { data: {} });
  expect(res.status()).toBe(202);
  const { job_id } = await res.json();
  await waitJob(request, job_id);
}

async function firstInsightId(
  request: APIRequestContext,
  ruleId: string,
): Promise<string> {
  const list = await request.get(`${API}/insights`, { params: { rule_id: ruleId } });
  expect(list.ok()).toBeTruthy();
  const items = ((await list.json()) as { items: { id: string }[] }).items;
  expect(items.length).toBeGreaterThan(0);
  return items[0].id;
}

async function investigateInsight(request: APIRequestContext, insightId: string) {
  const res = await request.post(`${API}/insights/${insightId}/investigate`, {
    data: { mode: "metadata_only" },
  });
  expect(res.status()).toBe(202);
  const { job_id } = await res.json();
  await waitJob(request, job_id, 180_000);
}

async function createBenchmarkFromInsight(request: APIRequestContext, insightId: string) {
  const res = await request.post(`${API}/insights/${insightId}/benchmark`, {
    data: { task_spec: OFFLINE_TASK_SPEC, repeat_count: 1 },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as { id: string; alternatives: { name: string }[] };
}

async function runAndCompare(request: APIRequestContext, benchmarkId: string, altName: string) {
  const started = await request.post(`${API}/benchmarks/${benchmarkId}/runs`, {
    data: { variants: ["baseline", altName], repeat_count: 1 },
  });
  expect(started.status()).toBe(202);
  await waitRuns(request, benchmarkId);
  const compared = await request.post(`${API}/benchmarks/${benchmarkId}/compare`, {
    data: { baseline_variant: "baseline", alternative_variant: altName },
  });
  expect(compared.ok()).toBeTruthy();
  return compared.json();
}

async function assertOverviewSpend(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Recorded spend")).toBeVisible();
  // CostValue or Simulated badge — spend should be non-empty / non-dash for seeded data.
  await expect(page.getByText("Simulated").first()).toBeVisible({ timeout: 30_000 });
}

test.describe("demo loop (offline)", () => {
  test.describe.configure({ mode: "serial", timeout: 600_000 });

  let projectId: string;
  let fixturePath: string;
  let retryInsightId: string;

  test.beforeAll(async ({ request }) => {
    fixturePath = initFixture();
    projectId = await ensureProject(request, fixturePath);
    expect(projectId).toBeTruthy();
    await setFakeScenario("success");
    await seedViaGateway();
    await analyze(request);
    retryInsightId = await firstInsightId(request, "retry_amplification");
  });

  test("verified savings path (PRD §18)", async ({ page, request }) => {
    await assertOverviewSpend(page);

    await page.goto("/insights");
    await expect(page.getByRole("link", { name: /retry_amplification/ }).first()).toBeVisible({
      timeout: 60_000,
    });

    await investigateInsight(request, retryInsightId);
    // UI investigate panel after API job (fresh load).
    await page.goto(`/insights/${retryInsightId}`);
    await expect(page.getByTestId("investigation-panel")).toBeVisible({ timeout: 60_000 });

    await setFakeScenario("success");
    const bench = await createBenchmarkFromInsight(request, retryInsightId);
    const alt = bench.alternatives[0]?.name ?? "targeted-context";
    const comparison = await runAndCompare(request, bench.id, alt);
    expect(comparison.comparison_status).toBe("verified");
    expect(comparison.correctness_preserved).toBe(true);
    expect(comparison.methodology).toBeTruthy();

    await page.goto(`/benchmarks/${bench.id}`);
    await expect(page.getByText("Verified savings").first()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("variables_changed").or(page.getByText("context_strategy")).first()).toBeVisible();

    const report = await request.get(`${API}/reports/project/${projectId}`, {
      params: { format: "json" },
    });
    expect(report.ok()).toBeTruthy();
    const body = await report.json();
    expect(body.benchmarks?.length ?? 0).toBeGreaterThan(0);
    const md = await request.get(`${API}/reports/project/${projectId}`, {
      params: { format: "markdown" },
    });
    expect(md.ok()).toBeTruthy();
    const markdown = await md.text();
    // FR-12: markdown must surface methodology, not only the word "Benchmark".
    expect(markdown).toMatch(/##\s*Methodology/i);
    expect(markdown).toMatch(/low_sample|variables_changed/);
  });

  test("fail-alt honesty path (Not an optimization)", async ({ page, request }) => {
    await setFakeScenario("fail-alt");
    // Fresh insight→benchmark so runs are independent of the verified path.
    const bench = await createBenchmarkFromInsight(request, retryInsightId);
    const alt = bench.alternatives[0]?.name ?? "targeted-context";
    const comparison = await runAndCompare(request, bench.id, alt);
    expect(comparison.correctness_preserved).toBe(false);
    expect(["measured", "inconclusive"]).toContain(comparison.comparison_status);

    await page.goto(`/benchmarks/${bench.id}`);
    await expect(page.getByText("Not an optimization").first()).toBeVisible({ timeout: 60_000 });
  });
});

import { expect, test } from "@playwright/test";

const BASE = new Date("2026-10-27T10:00:00.000Z");

function event(overrides: Record<string, unknown>) {
  return {
    provider: "fake",
    model_id: "fake-small",
    started_at: BASE.toISOString(),
    usage_source: "provider",
    status: "success",
    input_tokens: 1000,
    output_tokens: 100,
    external_session_id: "e2e-s1",
    request_fingerprint: "fp-b",
    ...overrides,
  };
}

test("insight evidence links to a recorded session", async ({ page, request }) => {
  const seed = await request.post("/api/tp/api/v1/usage/events", {
    data: [
      event({
        status: "error",
        error_category: "rate_limited",
        source_event_id: "ch-1",
        started_at: BASE.toISOString(),
      }),
      event({
        status: "error",
        error_category: "rate_limited",
        source_event_id: "ch-2",
        retry_of: "ch-1",
        started_at: new Date(BASE.getTime() + 10_000).toISOString(),
      }),
      event({
        source_event_id: "ch-3",
        retry_of: "ch-2",
        started_at: new Date(BASE.getTime() + 20_000).toISOString(),
      }),
    ],
  });
  expect(seed.ok()).toBeTruthy();

  await page.goto("/insights");
  await page.getByRole("button", { name: "Run analysis" }).click();
  const ruleRow = page.getByRole("link", { name: "retry_amplification.v1" });
  await expect(ruleRow).toBeVisible({ timeout: 60_000 });
  await ruleRow.click();

  const evidenceTable = page.getByTestId("evidence-table");
  await expect(evidenceTable).toBeVisible({ timeout: 15_000 });
  const evidenceLinks = evidenceTable.getByRole("link");
  await expect(evidenceLinks.first()).toBeVisible();
  expect(await evidenceLinks.count()).toBeGreaterThanOrEqual(1);

  await evidenceLinks.first().click();
  await expect(page).toHaveURL(/\/sessions\//);
  await expect(page.getByText("retry · attempt 2")).toBeVisible();
});

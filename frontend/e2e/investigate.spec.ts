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
    external_session_id: "e2e-investigate-s1",
    request_fingerprint: "fp-investigate",
    ...overrides,
  };
}

test("investigate discloses, confirms, and shows evidence-linked facts", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const seed = await request.post("/api/tp/api/v1/usage/events", {
    data: [
      event({
        status: "error",
        error_category: "rate_limited",
        source_event_id: "inv-ch-1",
        started_at: BASE.toISOString(),
      }),
      event({
        status: "error",
        error_category: "rate_limited",
        source_event_id: "inv-ch-2",
        retry_of: "inv-ch-1",
        started_at: new Date(BASE.getTime() + 10_000).toISOString(),
      }),
      event({
        source_event_id: "inv-ch-3",
        retry_of: "inv-ch-2",
        started_at: new Date(BASE.getTime() + 20_000).toISOString(),
      }),
    ],
  });
  expect(seed.ok()).toBeTruthy();

  // Both e2e specs share one database, so find the insight holding this
  // spec's seeded evidence instead of clicking a rule link that may match
  // several rows (detector upsert can also merge into one row).
  async function insightWithSeedEvidence(): Promise<string | null> {
    const list = await request.get("/api/tp/api/v1/insights", {
      params: { rule_id: "retry_amplification" },
    });
    expect(list.ok()).toBeTruthy();
    const body = await list.json();
    const ids = (body.items as { id: string }[]).map((item) => item.id);
    for (const id of ids) {
      const detail = await request.get(`/api/tp/api/v1/insights/${id}`);
      if (!detail.ok()) continue;
      const detailBody = await detail.json();
      const rows = detailBody.evidence_rows as {
        event?: { source_event_id?: string | null } | null;
      }[];
      if (rows.some((row) => row.event?.source_event_id?.startsWith("inv-ch-"))) {
        return id;
      }
    }
    return null;
  }

  await page.goto("/insights");
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page.getByText("Job: succeeded")).toBeVisible({ timeout: 90_000 });
  await expect.poll(insightWithSeedEvidence, { timeout: 60_000 }).not.toBeNull();
  const insightId = (await insightWithSeedEvidence()) as string;
  await page.goto(`/insights/${insightId}`);

  const investigateButton = page.getByRole("button", { name: "Investigate" });
  await expect(investigateButton).toBeVisible({ timeout: 15_000 });
  await investigateButton.click();
  const dialog = page.getByTestId("disclosure-dialog");
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await expect(dialog.getByText("metadata only").first()).toBeVisible();
  await expect(dialog.getByTestId("contributor-warning")).toBeVisible();

  await dialog.getByRole("button", { name: "Confirm and investigate" }).click();
  const panel = page.getByTestId("investigation-panel");
  await expect(panel).toBeVisible({ timeout: 120_000 });
  const evidenceLinks = panel.getByRole("link");
  await expect(evidenceLinks.first()).toBeVisible();
  expect(await evidenceLinks.count()).toBeGreaterThanOrEqual(1);
});

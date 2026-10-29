import { expect, test } from "@playwright/test";

test("settings renders privacy, thresholds, pricing, and retention sections", async ({
  page,
}) => {
  await page.goto("/settings");

  const privacy = page.getByTestId("privacy-section");
  await expect(privacy).toBeVisible({ timeout: 15_000 });
  await expect(privacy.getByText("Contributor mode: Meta may use", { exact: false })).toBeVisible();
  await expect(privacy.getByText("muse-spark-1.3-contributor", { exact: false })).toBeVisible();

  await expect(page.getByTestId("thresholds-section")).toBeVisible();
  await expect(page.getByTestId("pricing-section")).toBeVisible();
  await expect(page.getByTestId("retention-section")).toBeVisible();
});

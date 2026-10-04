import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const apiPort = process.env.PENGE_E2E_API_PORT ?? "8000";
  await page.route(`http://127.0.0.1:${apiPort}/**`, async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Synthetic Ask Penge browser journey" }),
    });
  });
});

test("fails closed without overflow and preserves the responsive workbench", async ({
  page,
}, testInfo) => {
  await page.goto("/ask");

  await expect(page.getByRole("heading", { name: "Ask Penge" })).toBeVisible();
  await expect(page.getByText("Exact HydraFusion is unavailable")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeDisabled();
  await expect(page.getByText(/No request has been sent/i)).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0);

  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: /Open evidence sheet/i }).click();
    await expect(page.getByRole("region", { name: "Answer evidence sheet" })).toBeVisible();
    await expect(page.getByText("No evidence items yet.")).toBeVisible();
    await page.getByRole("button", { name: "Close evidence sheet" }).click();
  } else {
    await expect(page.getByRole("complementary", { name: "Answer evidence" })).toBeVisible();
    await page.getByRole("button", { name: "Collapse evidence rail" }).click();
    await expect(page.getByRole("button", { name: "Expand evidence rail" })).toBeVisible();
  }

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(hasHorizontalOverflow).toBe(false);
});

test("does not simulate GitHub linkage or a synthetic financial answer", async ({ page }) => {
  await page.goto("/ask");

  await expect(page.getByRole("button", { name: "GitHub linking unavailable" })).toBeDisabled();
  await expect(page.getByText(/No local control can simulate a verified identity/i)).toBeVisible();
  await expect(page.getByText("Exact HydraFusion unavailable")).toBeVisible();
  await expect(page.getByText(/DKK 1\.42M/)).toHaveCount(0);
});

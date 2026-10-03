import { expect, test } from "@playwright/test";

test("real household API renders bank reports and persists category mutations", async ({
  page,
}, testInfo) => {
  const summaryResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/household/reports/summary") && response.status() === 200,
  );
  await page.goto("/household/report");
  await summaryResponse;
  await expect(page.getByText("Gross expenses", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview", exact: true })).toBeVisible();

  await page.getByRole("tab", { name: "Transactions", exact: true }).click();
  await expect(page.getByText("Synthetic mixed supermarket purchase").first()).toBeVisible();

  const categoriesResponse = page.waitForResponse(
    (response) => response.url().endsWith("/household/categories") && response.status() === 200,
  );
  await page.getByRole("tab", { name: "Categories", exact: true }).click();
  await categoriesResponse;
  await page.getByRole("button", { name: "Add expense category", exact: true }).click();
  const categoryName = `Synthetic browser ${testInfo.project.name}`;
  await page.getByLabel("Category name", { exact: true }).fill(categoryName);
  const mutation = page.waitForResponse(
    (response) =>
      response.url().endsWith("/household/categories") &&
      response.request().method() === "POST" &&
      response.status() === 201,
  );
  await page.getByRole("button", { name: "Create category", exact: true }).click();
  await mutation;
  await expect(page.getByRole("button", { name: categoryName, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: categoryName, exact: true })).toBeVisible();
});

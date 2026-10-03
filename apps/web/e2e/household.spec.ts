import { expect, test } from "@playwright/test";

test("real household API renders bank reports and persists category mutations", async ({
  page,
}, testInfo) => {
  await page.clock.setFixedTime(new Date("2026-06-30T12:00:00Z"));
  const summaryResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/household/reports/summary") && response.status() === 200,
  );
  const categoriesResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/household/categories" &&
      response.request().method() === "GET" &&
      response.status() === 200,
  );
  await page.goto("/household/report");
  await Promise.all([summaryResponse, categoriesResponse]);
  await expect(page.getByText("Gross expenses", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview", exact: true })).toBeVisible();

  await page.getByRole("tab", { name: "Transactions", exact: true }).click();
  await expect(page.getByText("Synthetic mixed supermarket purchase").first()).toBeVisible();

  const categoriesTab = page.getByRole("tab", { name: "Categories", exact: true });
  await categoriesTab.scrollIntoViewIfNeeded();
  await categoriesTab.click();
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
  const persistedCategories = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/household/categories" &&
      response.request().method() === "GET" &&
      response.status() === 200,
  );
  await page.reload();
  const persisted = await persistedCategories;
  expect(await persisted.json()).toEqual(
    expect.arrayContaining([expect.objectContaining({ name: categoryName })]),
  );
  await expect(page.getByRole("button", { name: categoryName, exact: true })).toBeVisible();
});

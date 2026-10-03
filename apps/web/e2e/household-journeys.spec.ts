import { expect, test, type Page, type Response } from "@playwright/test";

import {
  householdClassificationSchema,
  householdMerchantsResponseSchema,
  householdPreviewSchema,
  householdRulesResponseSchema,
  householdReportTransactionsSchema,
  householdTransactionSchema,
  householdTransactionsResponseSchema,
} from "../src/api/schemas";

const api = "http://127.0.0.1:8000";

function apiResponse(response: Response, path: string, method = "GET", status = 200): boolean {
  const url = new URL(response.url());
  return (
    url.origin === api &&
    url.pathname === path &&
    response.request().method() === method &&
    response.status() === status
  );
}

async function transactions(page: Page, label: string) {
  const response = await page.request.get(`${api}/household/transactions`, {
    params: { search: label, limit: 100 },
  });
  expect(response.status()).toBe(200);
  return householdTransactionsResponseSchema.parse(await response.json());
}

async function transaction(page: Page, id: string) {
  const response = await page.request.get(`${api}/household/transactions/${id}`);
  expect(response.status()).toBe(200);
  return householdTransactionSchema.parse(await response.json());
}

async function openTransaction(page: Page, label: string): Promise<void> {
  await page.getByLabel("Search transactions", { exact: true }).fill(label);
  await page
    .getByRole("table", { name: "Transactions for review" })
    .getByRole("button")
    .filter({ hasText: label })
    .click();
  await expect(page.getByRole("region", { name: `Transaction detail: ${label}` })).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-07-31T12:00:00Z"));
});

test("filtered report drilldown and keyboard bulk/split corrections conserve bank amounts", async ({
  page,
}, testInfo) => {
  const label = `Synthetic browser ${testInfo.project.name}`;
  await page.goto("/household/report");
  const drilldown = page.waitForResponse((response) =>
    apiResponse(response, "/household/reports/transactions"),
  );
  await page.getByRole("button", { name: `${label} essentials`, exact: true }).click();
  const report = householdReportTransactionsSchema.parse(await (await drilldown).json());
  expect(report.filters.category_id).not.toBeNull();
  expect(report.items).toHaveLength(1);
  expect(report.items[0]).toMatchObject({
    description: `${label} evidence`,
    signed_amount_native: "-10.0000",
    matching_split_amount_native: "-10.0000",
  });
  await expect(
    page.getByRole("table", { name: "Matching household bank transactions" }),
  ).toContainText(`${label} evidence`);

  await page.getByRole("tab", { name: "Transactions", exact: true }).click();
  await page.getByLabel("Search transactions", { exact: true }).fill(`${label} bulk`);
  const selectAll = page.getByRole("checkbox", { name: "Select all visible transactions" });
  await selectAll.focus();
  await page.keyboard.press("Space");
  await expect(page.getByText("2 selected", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Assign category", exact: true }).click();
  await page.getByRole("option", { name: `${label} essentials`, exact: true }).click();
  await page.getByRole("button", { name: "Apply to selected", exact: true }).click();
  await expect
    .poll(async () => {
      const rows = await transactions(page, `${label} bulk`);
      return rows.filter((row) => row.classification?.provenance === "manual").length;
    })
    .toBe(2);

  await openTransaction(page, `${label} bulk one`);
  const editor = page.getByLabel("Transaction split editor", { exact: true });
  await editor.getByLabel("Amount 1 (EUR)", { exact: true }).fill("-8.00");
  await editor.getByRole("button", { name: "Add split", exact: true }).click();
  await editor.getByRole("combobox", { name: "Category 2", exact: true }).click();
  await page.getByRole("option", { name: `${label} extras`, exact: true }).click();
  await editor.getByLabel("Amount 2 (EUR)", { exact: true }).fill("-11.99");
  await expect(editor.getByRole("button", { name: "Save split", exact: true })).toBeDisabled();
  await editor.getByLabel("Amount 2 (EUR)", { exact: true }).fill("-12.00");
  const saved = page.waitForResponse(
    (response) =>
      response.url().startsWith(`${api}/household/transactions/`) &&
      response.url().endsWith("/classification") &&
      response.request().method() === "PATCH" &&
      response.status() === 200,
  );
  await editor.getByRole("button", { name: "Save split", exact: true }).click();
  const classification = householdClassificationSchema.parse(await (await saved).json());
  expect(classification.allocations.map(({ amount }) => amount).sort()).toEqual([
    "-12.0000",
    "-8.0000",
  ]);
  await page.reload();
  const persisted = await transaction(page, classification.transaction_id);
  expect(persisted.amount).toBe("-20.0000");
  expect(persisted.classification).toMatchObject({
    provenance: "manual",
    allocations: classification.allocations,
  });
});

test("local vendor provenance and stale merchant save use real revision guards", async ({
  page,
}, testInfo) => {
  const label = `Synthetic browser ${testInfo.project.name}`;
  await page.goto("/household/merchants");
  await expect(
    page.getByRole("region", { name: "Public merchant reference status" }),
  ).toContainText("2 entries");
  await page.getByRole("combobox", { name: "Merchant", exact: true }).click();
  await page.getByRole("option", { name: `${label} merchant`, exact: true }).click();
  await page.getByLabel("Merchant name or alias", { exact: true }).fill(`${label} public`);
  await page.getByLabel("Merchant name or alias", { exact: true }).press("Enter");
  const linked = page.waitForResponse(
    (response) =>
      response.url().startsWith(`${api}/household/merchants/`) &&
      response.request().method() === "PATCH" &&
      response.status() === 200,
  );
  await page.getByRole("button", { name: `Link reference ${label} public`, exact: true }).click();
  await linked;
  await expect(page.getByText(/Public reference: name-suggestion-index/)).toContainText(
    `synthetic-browser-${testInfo.project.name}`,
  );
  await expect(page.getByLabel("Normalized merchant name", { exact: true })).toHaveValue(
    `${label} merchant`,
  );
  await page.getByLabel("Provider", { exact: true }).fill("gls");
  await page.getByLabel("Normalized provider alias", { exact: true }).fill(`${label} alternate`);
  await page.getByRole("checkbox", { name: "Confirm this household alias", exact: true }).check();
  const alias = page.waitForResponse((response) =>
    apiResponse(response, "/household/aliases", "POST", 201),
  );
  await page.getByRole("button", { name: "Add alias", exact: true }).click();
  await alias;
  await expect(page.getByRole("button", { name: `Edit alias ${label} alternate` })).toBeVisible();

  const merchantResponse = await page.request.get(`${api}/household/merchants`);
  const merchant = householdMerchantsResponseSchema
    .parse(await merchantResponse.json())
    .find(({ name }) => name === `${label} merchant`);
  expect(merchant).toBeDefined();
  if (merchant === undefined) throw new Error("Synthetic merchant is missing");
  expect(merchant.reference_source).toBe("name-suggestion-index");
  const concurrent = await page.request.patch(`${api}/household/merchants/${merchant.id}`, {
    data: {
      expected_revision: merchant.revision,
      name: merchant.name,
      identity_kind: merchant.identity_kind,
      confirmed: merchant.confirmed,
      reference_source: merchant.reference_source,
      reference_key: merchant.reference_key,
      reference_version: merchant.reference_version,
    },
  });
  expect(concurrent.status()).toBe(200);
  const rejected = page.waitForResponse((response) =>
    apiResponse(response, `/household/merchants/${merchant.id}`, "PATCH", 409),
  );
  await page.getByRole("button", { name: "Save merchant identity", exact: true }).click();
  await rejected;
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: /revision|changed|conflict/i })
      .first(),
  ).toBeVisible();
  await page.reload();
  const persisted = householdMerchantsResponseSchema
    .parse(await (await page.request.get(`${api}/household/merchants`)).json())
    .find(({ id }) => id === merchant.id);
  expect(persisted).toMatchObject({
    name: merchant.name,
    confirmed: true,
    reference_key: `synthetic-browser-${testInfo.project.name}`,
  });
});

test("historical rule approval protects manual evidence and PayPal details never duplicate banks", async ({
  page,
}, testInfo) => {
  const label = `Synthetic browser ${testInfo.project.name}`;
  const before = await transactions(page, label);
  const evidence = before.find(({ description }) => description === `${label} evidence`);
  const history = before.find(({ description }) => description === `${label} history`);
  expect(history?.classification).toBeNull();
  if (evidence === undefined || history === undefined)
    throw new Error("Synthetic history is missing");
  await page.goto("/household/rules");
  const merchantRows = householdMerchantsResponseSchema.parse(
    await (await page.request.get(`${api}/household/merchants`)).json(),
  );
  const merchant = merchantRows.find(({ name }) => name === `${label} merchant`);
  const rules = householdRulesResponseSchema.parse(
    await (await page.request.get(`${api}/household/rules`)).json(),
  );
  const activeRule = rules.find(
    ({ merchant_id, state }) => merchant_id === merchant?.id && state === "active",
  );
  if (activeRule === undefined) throw new Error("Synthetic active rule is missing");
  const rule = page.getByRole("region", {
    name: `Rule for ${label} merchant, version ${activeRule.version}`,
    exact: true,
  });
  const previewResponse = page.waitForResponse(
    (response) =>
      response.url().startsWith(`${api}/household/rules/`) &&
      response.url().endsWith("/preview") &&
      response.request().method() === "POST",
  );
  await rule.getByRole("button", { name: "Preview historical reapply", exact: true }).click();
  const preview = householdPreviewSchema.parse(await (await previewResponse).json());
  expect(preview.candidates.map(({ transaction_id }) => transaction_id)).toEqual([
    history.transaction_id,
  ]);
  expect((await transaction(page, history.transaction_id)).classification).toBeNull();
  const apply = page.getByRole("button", { name: "Apply approved preview", exact: true });
  await expect(apply).toBeDisabled();
  await page
    .getByRole("checkbox", {
      name: "I reviewed this historical reapplication preview",
      exact: true,
    })
    .check();
  const applied = page.waitForResponse((response) =>
    apiResponse(response, `/household/previews/${preview.id}/apply`, "POST"),
  );
  await apply.click();
  await applied;
  expect((await transaction(page, history.transaction_id)).classification?.provenance).toBe("rule");
  expect((await transaction(page, evidence.transaction_id)).classification).toEqual(
    evidence.classification,
  );

  await page.goto("/household");
  await openTransaction(page, `${label} paypal`);
  await page.getByRole("combobox", { name: "Treatment", exact: true }).click();
  await page.getByRole("option", { name: "Expense", exact: true }).click();
  await page.getByRole("combobox", { name: "Category", exact: true }).fill(`${label} essentials`);
  await page.getByRole("option", { name: `${label} essentials`, exact: true }).click();
  const correction = page.waitForResponse(
    (response) =>
      response.url().startsWith(`${api}/household/transactions/`) &&
      response.url().endsWith("/classification") &&
      response.request().method() === "PATCH" &&
      response.status() === 200,
  );
  await page.getByRole("button", { name: "Save correction", exact: true }).click();
  const manual = householdClassificationSchema.parse(await (await correction).json());
  expect(manual.provenance).toBe("manual");
  expect(manual.allocations).toHaveLength(1);
  for (const item of ["a", "b"]) {
    await page
      .getByRole("checkbox", { name: `Select PayPal detail ${label} detail ${item}` })
      .check();
  }
  const amounts = page.getByLabel("Signed bank amount (EUR)", { exact: true });
  await amounts.nth(0).fill("-20.00");
  await amounts.nth(1).fill("-21.99");
  const approve = page.getByRole("button", { name: "Approve selected PayPal links", exact: true });
  await page
    .getByRole("checkbox", {
      name: "I verified these provider details belong to this bank movement",
    })
    .check();
  await expect(approve).toBeDisabled();
  await amounts.nth(1).fill("-22.00");
  await page
    .getByRole("checkbox", {
      name: "I verified these provider details belong to this bank movement",
    })
    .check();
  const reconciled = page.waitForResponse(
    (response) =>
      response.url().startsWith(`${api}/household/transactions/`) &&
      response.url().endsWith("/classification") &&
      response.request().method() === "PATCH" &&
      response.status() === 200,
  );
  await approve.click();
  const classification = householdClassificationSchema.parse(await (await reconciled).json());
  expect(classification.detail_links.map(({ bank_amount }) => bank_amount).sort()).toEqual([
    "-20.0000",
    "-22.0000",
  ]);
  expect(classification.allocations).toEqual(manual.allocations);
  await expect(page.getByText("Approved detail", { exact: true })).toHaveCount(2);
  await page.reload();
  const after = await transactions(page, label);
  expect(after.map(({ transaction_id, amount }) => ({ transaction_id, amount }))).toEqual(
    before.map(({ transaction_id, amount }) => ({ transaction_id, amount })),
  );
  expect(
    (await transaction(page, classification.transaction_id)).classification?.detail_links,
  ).toEqual(classification.detail_links);
});

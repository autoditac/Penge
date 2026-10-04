/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HouseholdPage } from "../src/pages/Household";
import { NotificationsProvider } from "../src/components/Notifications";
import { fetchHouseholdReportSummary } from "../src/api/householdReportsClient";
import type { components } from "../src/api/schema";
import {
  householdClassificationSchema,
  type HouseholdTransactionResponse,
} from "../src/api/schemas";
import { reportCurrencyView } from "../src/household/reporting";
import { renderWithTheme } from "./test-utils";

type ClassificationWrite = components["schemas"]["ClassificationWrite"];

vi.mock("../src/components/EChart", () => ({
  EChart: ({ ariaLabel }: { readonly ariaLabel: string }) => (
    <div role="img" aria-label={ariaLabel} />
  ),
}));

const amount = { amount: "100.00", known_subtotal: "100.00", complete: true, missing_count: 0 };
const pair = { eur: amount, dkk: amount };
const totals = {
  income: pair,
  gross_expenses: pair,
  refunds: pair,
  net_expenses: pair,
  surplus: pair,
};
const coverage = {
  history_start: "2025-07-01",
  history_completeness: "unknown",
  bank_transaction_count: 1,
  included_transaction_count: 1,
  unclassified_transaction_count: 1,
  unclassified_expense_count: 1,
  unclassified_expense_amount: pair,
  transfer_excluded_count: 0,
  excluded_transaction_count: 0,
  classification_review_count: 0,
  source_snapshot_drift_count: 0,
  allocation_mismatch_count: 0,
  missing_fx_allocation_count: 0,
  payment_detail_link_count: 0,
  payment_detail_reconciled_count: 0,
  payment_detail_review_count: 0,
  payment_detail_stale_count: 0,
  payment_detail_unmatched_count: 0,
};
const freshness = {
  report_generated_at: "2026-10-03T12:00:00Z",
  latest_bank_booking_date: "2026-10-01",
  latest_bank_import_at: null,
  latest_fx_rate_date: null,
  latest_payment_detail_sync_at: null,
};
const category = {
  id: "category-expense",
  parent_id: null,
  name: "Synthetic groceries",
  kind: "expense",
  sort_order: 0,
  archived: false,
  revision: 1,
};
const merchant = {
  archived: false,
  confirmed: true,
  id: "merchant-1",
  identity_kind: "stable",
  name: "Synthetic Grocer",
  reference_key: null,
  reference_source: null,
  reference_version: null,
  revision: 2,
  rule_version: 0,
};
const transaction: HouseholdTransactionResponse = {
  account_id: "account-1",
  amount: "-42.30",
  classification: null,
  counterparty: "SYNTHETIC GROCER 004",
  currency: "EUR",
  description: "Synthetic card payment",
  kind: "card",
  provider: "synthetic-bank",
  reporting_role: "bank_movement",
  transaction_id: "transaction-1",
  ts: "2026-10-03T12:00:00Z",
};

function classificationFromRequest(
  body: ClassificationWrite,
  sourceTransaction: HouseholdTransactionResponse = transaction,
) {
  return householdClassificationSchema.parse({
    allocations: body.allocations ?? [],
    detail_changed: false,
    detail_links: body.detail_links ?? [],
    explanation: body.explanation,
    identity_confirmed: body.identity_confirmed ?? false,
    links: body.links ?? [],
    merchant_id: body.merchant_id ?? null,
    provenance: "manual",
    review_state: "classified",
    revision: 1,
    rule_id: null,
    source_amount: sourceTransaction.amount,
    source_changed: false,
    source_counterparty: sourceTransaction.counterparty,
    source_currency: sourceTransaction.currency,
    source_kind: sourceTransaction.kind,
    source_ts: sourceTransaction.ts,
    transaction_id: sourceTransaction.transaction_id,
    treatment: body.treatment,
  });
}

function installReviewApi(
  requests: Array<{ readonly url: URL; readonly init: RequestInit | undefined }>,
  patchStatus = 200,
  sourceTransaction = transaction,
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: URL, init?: RequestInit) => {
      const url = new URL(input);
      requests.push({ url, init });
      if (url.pathname === "/accounts") {
        return new Response("[]", { status: 200 });
      }
      if (url.pathname === "/household/categories") {
        return new Response(JSON.stringify([category]), { status: 200 });
      }
      if (url.pathname === "/household/merchants") {
        return new Response(JSON.stringify([merchant]), { status: 200 });
      }
      if (
        url.pathname === "/household/aliases" ||
        url.pathname === "/household/rules" ||
        url.pathname === "/household/payment-details" ||
        url.pathname === "/household/audit"
      ) {
        return new Response("[]", { status: 200 });
      }
      if (url.pathname === `/household/transactions/${sourceTransaction.transaction_id}`) {
        return new Response(JSON.stringify(sourceTransaction), { status: 200 });
      }
      if (
        url.pathname ===
          `/household/transactions/${sourceTransaction.transaction_id}/classification` &&
        init?.method === "PATCH"
      ) {
        if (patchStatus !== 200) {
          return new Response(JSON.stringify({ detail: "stale revision; reload and retry" }), {
            status: patchStatus,
          });
        }
        const body = JSON.parse(String(init.body)) as ClassificationWrite;
        return new Response(JSON.stringify(classificationFromRequest(body, sourceTransaction)), {
          status: 200,
        });
      }
      if (url.pathname === "/household/transactions") {
        return new Response(JSON.stringify([sourceTransaction]), { status: 200 });
      }
      throw new Error(`Unexpected API route ${url.pathname}`);
    }),
  );
}

function filtersFromUrl(url: URL) {
  return {
    since: url.searchParams.get("since"),
    until: url.searchParams.get("until"),
    granularity: url.searchParams.get("granularity"),
    account_ids: url.searchParams.getAll("account_id"),
    entity_ids: url.searchParams.getAll("entity_id"),
    category_id: url.searchParams.get("category_id"),
  };
}

function renderPage(path: string): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  renderWithTheme(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <NotificationsProvider>
          <HouseholdPage />
        </NotificationsProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("household live API wiring", () => {
  it("writes explicit first-time merchant confirmation with the category correction", async () => {
    const user = userEvent.setup();
    const requests: Array<{ readonly url: URL; readonly init: RequestInit | undefined }> = [];
    installReviewApi(requests);

    renderPage("/household");
    await user.click(
      await screen.findByRole("button", {
        name: "SYNTHETIC GROCER 004 Synthetic card payment",
      }),
    );
    await user.click(await screen.findByRole("combobox", { name: "Household merchant" }));
    await user.click(await screen.findByRole("option", { name: "Synthetic Grocer" }));
    await user.click(
      screen.getByRole("checkbox", {
        name: "I confirm this transaction is from the selected merchant",
      }),
    );
    await user.click(screen.getByRole("combobox", { name: "Treatment" }));
    await user.click(await screen.findByRole("option", { name: "Expense" }));
    await user.click(screen.getByRole("combobox", { name: "Category" }));
    await user.click(await screen.findByRole("option", { name: "Synthetic groceries" }));
    await user.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByText("Transaction correction saved.")).toBeInTheDocument();

    const write = requests.find(
      ({ url, init }) =>
        url.pathname === `/household/transactions/${transaction.transaction_id}/classification` &&
        init?.method === "PATCH",
    );
    expect(write).toBeDefined();
    expect(JSON.parse(String(write?.init?.body))).toMatchObject({
      expected_revision: 0,
      treatment: "expense",
      merchant_id: merchant.id,
      identity_confirmed: true,
      allocations: [{ category_id: category.id, amount: transaction.amount }],
    });
  });

  it("keeps bulk categorization from confirming a first merchant identity", async () => {
    const user = userEvent.setup();
    const requests: Array<{ readonly url: URL; readonly init: RequestInit | undefined }> = [];
    installReviewApi(requests);

    renderPage("/household");
    await user.click(
      await screen.findByRole("checkbox", { name: "Select Synthetic card payment" }),
    );
    await user.click(screen.getByRole("combobox", { name: "Assign category" }));
    await user.click(await screen.findByRole("option", { name: "Synthetic groceries" }));
    await user.click(screen.getByRole("button", { name: "Apply to selected" }));
    expect(await screen.findByText("1 transaction correction saved.")).toBeInTheDocument();

    const write = requests.find(
      ({ url, init }) =>
        url.pathname === `/household/transactions/${transaction.transaction_id}/classification` &&
        init?.method === "PATCH",
    );
    expect(JSON.parse(String(write?.init?.body))).toMatchObject({
      merchant_id: null,
      identity_confirmed: false,
    });
  });

  it("clears an existing merchant identity when the reviewer explicitly selects none", async () => {
    const user = userEvent.setup();
    const requests: Array<{ readonly url: URL; readonly init: RequestInit | undefined }> = [];
    const classifiedTransaction = {
      ...transaction,
      classification: {
        ...classificationFromRequest({
          expected_revision: 0,
          allocations: [{ category_id: category.id, amount: transaction.amount }],
          detail_links: [],
          explanation: "Previously confirmed synthetic merchant.",
          identity_confirmed: true,
          links: [],
          merchant_id: merchant.id,
          treatment: "expense",
        }),
        revision: 3,
      },
    };
    installReviewApi(requests, 200, classifiedTransaction);

    renderPage("/household");
    await user.click(
      await screen.findByRole("button", {
        name: "Synthetic Grocer Synthetic card payment",
      }),
    );
    await user.click(await screen.findByRole("combobox", { name: "Household merchant" }));
    await user.click(await screen.findByRole("option", { name: "No merchant identity" }));
    await user.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByText("Transaction correction saved.")).toBeInTheDocument();

    const write = requests.find(
      ({ url, init }) =>
        url.pathname === `/household/transactions/${transaction.transaction_id}/classification` &&
        init?.method === "PATCH",
    );
    expect(JSON.parse(String(write?.init?.body))).toMatchObject({
      expected_revision: 3,
      merchant_id: null,
      identity_confirmed: false,
    });
  });

  it("surfaces a stale merchant-classification write without reporting success", async () => {
    const user = userEvent.setup();
    const requests: Array<{ readonly url: URL; readonly init: RequestInit | undefined }> = [];
    installReviewApi(requests, 409);

    renderPage("/household");
    await user.click(
      await screen.findByRole("button", {
        name: "SYNTHETIC GROCER 004 Synthetic card payment",
      }),
    );
    await user.click(await screen.findByRole("combobox", { name: "Household merchant" }));
    await user.click(await screen.findByRole("option", { name: "Synthetic Grocer" }));
    await user.click(
      screen.getByRole("checkbox", {
        name: "I confirm this transaction is from the selected merchant",
      }),
    );
    await user.click(screen.getByRole("combobox", { name: "Treatment" }));
    await user.click(await screen.findByRole("option", { name: "Expense" }));
    await user.click(screen.getByRole("combobox", { name: "Category" }));
    await user.click(await screen.findByRole("option", { name: "Synthetic groceries" }));
    await user.click(screen.getByRole("button", { name: "Save correction" }));

    expect(await screen.findByText("stale revision; reload and retry")).toBeInTheDocument();
    expect(screen.queryByText("Transaction correction saved.")).not.toBeInTheDocument();
  });

  it("renders validated reports and keeps exact category drilldown filters", async () => {
    const requests: URL[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: URL) => {
        const url = new URL(input);
        requests.push(url);
        const filters = filtersFromUrl(url);
        let body: unknown;
        if (url.pathname === "/accounts") {
          body = [];
        } else if (url.pathname === "/household/categories") {
          body = [category];
        } else if (url.pathname === "/household/reports/summary") {
          body = {
            filters,
            current: { since: filters.since, until: filters.until, totals },
            previous: { since: "2026-09-01", until: "2026-09-03", totals },
            change: totals,
            points: [],
            coverage,
            freshness,
          };
        } else if (url.pathname === "/household/reports/categories") {
          body = {
            filters,
            categories: [
              {
                ...category,
                category_id: category.id,
                totals,
                children: [],
                transaction_count: 1,
              },
            ],
            coverage,
            freshness,
          };
        } else if (url.pathname === "/household/reports/transactions") {
          body = { filters, search: null, items: [], limit: 100, offset: 0, total: 0 };
        } else {
          throw new Error(`Unexpected API route ${url.pathname}`);
        }
        return new Response(JSON.stringify(body), { status: 200 });
      }),
    );
    renderPage("/household/report");
    const categoryButton = await screen.findByRole("button", { name: "Synthetic groceries" });
    expect(screen.getByText(/cannot certify complete history coverage/)).toBeInTheDocument();
    expect(screen.getByText(/unclassified expenses, remain included/)).toBeInTheDocument();
    await userEvent.setup().click(categoryButton);
    await screen.findByText(/matching household bank transactions/i);
    const drilldown = requests.find((url) => url.pathname === "/household/reports/transactions");
    expect(drilldown).toBeDefined();
    const summary = requests.find((url) => url.pathname === "/household/reports/summary");
    expect(drilldown?.searchParams.get("category_id")).toBe(category.id);
    for (const key of ["since", "until", "granularity"]) {
      expect(drilldown?.searchParams.get(key)).toBe(summary?.searchParams.get(key));
    }
  });

  it("serializes repeated account/member filters without comma joins", async () => {
    const fetch = vi.fn(async (_url: URL) => new Response(JSON.stringify({}), { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    await expect(
      fetchHouseholdReportSummary({
        since: "2026-04-01",
        until: "2026-04-30",
        granularity: "month",
        accountIds: ["checking-a", "checking-b"],
        entityIds: ["member-a", "member-b"],
        categoryId: null,
      }),
    ).rejects.toThrow("503");
    const call: unknown = fetch.mock.calls[0]?.[0];
    expect(call).toBeInstanceOf(URL);
    if (!(call instanceof URL)) {
      throw new Error("Expected a URL for the real API request.");
    }
    expect(call.searchParams.getAll("account_id")).toEqual(["checking-a", "checking-b"]);
    expect(call.searchParams.getAll("entity_id")).toEqual(["member-a", "member-b"]);
    expect(call.searchParams.has("category_id")).toBe(false);
  });

  it("shows missing report APIs as errors rather than synthesized dashboard totals", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: URL) =>
        input.pathname === "/accounts" || input.pathname === "/household/categories"
          ? new Response("[]", { status: 200 })
          : new Response(JSON.stringify({ detail: "Household reports unavailable" }), {
              status: 503,
            }),
      ),
    );
    renderPage("/household/report");
    expect(await screen.findByText(/Household reports unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("Income, expenses and surplus")).not.toBeInTheDocument();
  });

  it("loads local merchant-reference data and links explicit provenance to a selected merchant", async () => {
    const user = userEvent.setup();
    const requests: Array<{ readonly url: URL; readonly init: RequestInit | undefined }> = [];
    const referenceMerchant = {
      archived: false,
      confirmed: true,
      id: "merchant-1",
      identity_kind: "stable",
      name: "Synthetic Grocer",
      reference_key: null,
      reference_source: null,
      reference_version: null,
      revision: 2,
      rule_version: 1,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: URL, init?: RequestInit) => {
        const url = new URL(input);
        requests.push({ url, init });
        if (url.pathname === "/household/merchants") {
          return new Response(JSON.stringify([referenceMerchant]), { status: 200 });
        }
        if (url.pathname === "/household/aliases") {
          return new Response("[]", { status: 200 });
        }
        if (url.pathname === "/vendors/reference-index/status") {
          return new Response(
            JSON.stringify({
              active_generation_id: "d84e0be0-cf77-4c80-9154-f7a8b53c2e75",
              attribution: "Name Suggestion Index",
              attribution_url: "https://example.invalid/attribution",
              candidate_integrity: null,
              candidate_version: null,
              checksum_sha256: "synthetic-sha256",
              error_code: null,
              error_message: null,
              last_attempt_at: null,
              last_checked_at: "2026-10-03T09:00:00Z",
              last_success_at: "2026-10-02T09:00:00Z",
              license: "BSD-3-Clause",
              package_integrity: null,
              record_count: 42,
              snapshot_completed_at: "2026-10-02T09:05:00Z",
              snapshot_started_at: "2026-10-02T09:00:00Z",
              source_generated_at: "2026-10-01T09:00:00Z",
              source_id: "name-suggestion-index",
              source_url: "https://example.invalid/source",
              source_version: "synthetic-v1",
              status: "current",
            }),
            { status: 200 },
          );
        }
        if (url.pathname === "/vendors/reference-index/search") {
          return new Response(
            JSON.stringify({
              limit: 20,
              match_status: "unique",
              matches: [
                {
                  aliases: ["Synthetic Grocers"],
                  category_path: "shop/supermarket",
                  label: "Synthetic Grocer",
                  license: "BSD-3-Clause",
                  match_kind: "exact_alias",
                  source_entity_id: "nsi-entity-42",
                  source_url: "https://example.invalid/entity/42",
                  source_version: "synthetic-v1",
                  wikidata_id: null,
                },
              ],
              source_status: "current",
              source_version: "synthetic-v1",
              truncated: false,
            }),
            { status: 200 },
          );
        }
        if (url.pathname === "/household/merchants/merchant-1" && init?.method === "PATCH") {
          return new Response(
            JSON.stringify({
              ...referenceMerchant,
              reference_key: "nsi-entity-42",
              reference_source: "name-suggestion-index",
              reference_version: "synthetic-v1",
              revision: 3,
            }),
            { status: 200 },
          );
        }
        throw new Error(`Unexpected API route ${url.pathname}`);
      }),
    );

    renderPage("/household/merchants");
    expect(await screen.findByText(/version synthetic-v1/)).toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "Merchant" }));
    await user.click(await screen.findByRole("option", { name: "Synthetic Grocer" }));
    await user.type(screen.getByRole("textbox", { name: "Merchant name or alias" }), "Synthetic");
    await user.click(screen.getByRole("button", { name: "Search index" }));
    await user.click(
      await screen.findByRole("button", { name: "Link reference Synthetic Grocer" }),
    );

    const search = requests.find(({ url }) => url.pathname === "/vendors/reference-index/search");
    expect(search?.url.searchParams.get("q")).toBe("Synthetic");
    expect(search?.url.searchParams.get("limit")).toBe("20");
    const update = requests.find(
      ({ url, init }) =>
        url.pathname === "/household/merchants/merchant-1" && init?.method === "PATCH",
    );
    expect(update).toBeDefined();
    expect(JSON.parse(String(update?.init?.body))).toMatchObject({
      expected_revision: 2,
      reference_key: "nsi-entity-42",
      reference_source: "name-suggestion-index",
      reference_version: "synthetic-v1",
    });
  });

  it("shows reference-index API failures without inventing source status or matches", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: URL) => {
        const url = new URL(input);
        if (url.pathname === "/household/merchants" || url.pathname === "/household/aliases") {
          return new Response("[]", { status: 200 });
        }
        if (url.pathname === "/vendors/reference-index/status") {
          return new Response(JSON.stringify({ detail: "Reference status unavailable" }), {
            status: 503,
          });
        }
        if (url.pathname === "/vendors/reference-index/search") {
          return new Response(JSON.stringify({ detail: "Reference search unavailable" }), {
            status: 503,
          });
        }
        throw new Error(`Unexpected API route ${url.pathname}`);
      }),
    );

    renderPage("/household/merchants");
    expect(await screen.findByText(/Reference status unavailable/)).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Merchant name or alias" }), "Synthetic");
    await user.click(screen.getByRole("button", { name: "Search index" }));
    expect(await screen.findByText(/Reference search unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("no match")).not.toBeInTheDocument();
  });

  it("preserves incomplete currency subtotal and rejects contradictory completeness", () => {
    expect(
      reportCurrencyView({
        amount: null,
        known_subtotal: "42.30",
        complete: false,
        missing_count: 1,
      }),
    ).toEqual({ amount: null, knownSubtotal: "42.30", complete: false });
    expect(() =>
      reportCurrencyView({
        amount: null,
        known_subtotal: "42.30",
        complete: true,
        missing_count: 1,
      }),
    ).toThrow("completeness");
  });
});

/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HouseholdPage } from "../src/pages/Household";
import { NotificationsProvider } from "../src/components/Notifications";
import { fetchHouseholdReportSummary } from "../src/api/householdReportsClient";
import { reportCurrencyView } from "../src/household/reporting";
import { renderWithTheme } from "./test-utils";

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
      rule_version: 1,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: URL, init?: RequestInit) => {
        const url = new URL(input);
        requests.push({ url, init });
        if (url.pathname === "/household/merchants") {
          return new Response(JSON.stringify([merchant]), { status: 200 });
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
              ...merchant,
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

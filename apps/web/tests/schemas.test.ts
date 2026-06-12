import { describe, expect, it } from "vitest";

import {
  accountsResponseSchema,
  allocationResponseSchema,
  benchmarkSeriesResponseSchema,
  benchmarksResponseSchema,
  cashflowSeriesResponseSchema,
  feesResponseSchema,
  freshnessResponseSchema,
  netWorthTotalSeriesResponseSchema,
  returnsSeriesResponseSchema,
  returnsSummaryResponseSchema,
} from "../src/api/schemas";
import {
  demoAccounts,
  demoAllocation,
  demoBenchmarkDaily,
  demoBenchmarks,
  demoCashflowDaily,
  demoFees,
  demoFreshness,
  demoNetWorthTotal,
  demoReturnsDaily,
  demoReturnsSummary,
} from "../src/demo/fixtures";

describe("api schemas", () => {
  it("accept every demo fixture (fixtures stay contract-conformant)", () => {
    expect(() => accountsResponseSchema.parse(demoAccounts)).not.toThrow();
    expect(() => netWorthTotalSeriesResponseSchema.parse(demoNetWorthTotal)).not.toThrow();
    expect(() => cashflowSeriesResponseSchema.parse(demoCashflowDaily)).not.toThrow();
    expect(() => freshnessResponseSchema.parse(demoFreshness)).not.toThrow();
    for (const by of ["kind", "currency", "entity"] as const) {
      expect(() => allocationResponseSchema.parse(demoAllocation(by))).not.toThrow();
    }
  });

  it("accept the returns/benchmark/fee demo fixtures (#206)", () => {
    for (const scope of ["household", "account", "asset_class"] as const) {
      expect(() => returnsSeriesResponseSchema.parse(demoReturnsDaily(scope))).not.toThrow();
      expect(() => returnsSummaryResponseSchema.parse(demoReturnsSummary(scope))).not.toThrow();
    }
    expect(() => benchmarksResponseSchema.parse(demoBenchmarks)).not.toThrow();
    const benchmarkId = demoBenchmarks[0]?.instrument_id ?? "demo";
    expect(() =>
      benchmarkSeriesResponseSchema.parse(demoBenchmarkDaily(benchmarkId)),
    ).not.toThrow();
    expect(() => feesResponseSchema.parse(demoFees)).not.toThrow();
  });

  it("reject malformed decimal strings", () => {
    const broken = {
      ...demoNetWorthTotal,
      points: [{ as_of: "2026-01-01", balance_dkk: "12,5", balance_eur: null }],
    };
    expect(netWorthTotalSeriesResponseSchema.safeParse(broken).success).toBe(false);
  });

  it("reject malformed dates", () => {
    const broken = {
      ...demoNetWorthTotal,
      points: [{ as_of: "01/01/2026", balance_dkk: "1.0", balance_eur: null }],
    };
    expect(netWorthTotalSeriesResponseSchema.safeParse(broken).success).toBe(false);
  });

  it("reject unknown allocation dimensions", () => {
    const broken = { ...demoAllocation("kind"), by: "provider" };
    expect(allocationResponseSchema.safeParse(broken).success).toBe(false);
  });

  it("accept nullable balances and freshness dates", () => {
    const payload = {
      limit: 10,
      offset: 0,
      total: 1,
      points: [{ as_of: "2026-01-01", balance_dkk: null, balance_eur: null }],
    };
    expect(() => netWorthTotalSeriesResponseSchema.parse(payload)).not.toThrow();
    expect(() =>
      freshnessResponseSchema.parse({
        marts: [{ mart: "mart_net_worth_daily", row_count: 0, latest_as_of: null }],
      }),
    ).not.toThrow();
  });
});

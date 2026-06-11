import { describe, expect, it } from "vitest";

import type { CashflowPoint, NetWorthTotalPoint } from "../src/api/schemas";
import {
  allocationData,
  latestNetWorth,
  monthlyCashflow,
  netWorthSeries,
  periodChange,
} from "../src/transforms";

const points: NetWorthTotalPoint[] = [
  { as_of: "2026-01-01", balance_dkk: "1000.0000", balance_eur: "134.0000" },
  { as_of: "2026-01-02", balance_dkk: null, balance_eur: "135.0000" },
  { as_of: "2026-01-03", balance_dkk: "1100.0000", balance_eur: "147.0000" },
];

describe("netWorthSeries", () => {
  it("builds [date, value] pairs and skips null balances", () => {
    expect(netWorthSeries(points, "DKK")).toEqual([
      ["2026-01-01", 1000],
      ["2026-01-03", 1100],
    ]);
    expect(netWorthSeries(points, "EUR")).toHaveLength(3);
  });
});

describe("latestNetWorth / periodChange", () => {
  it("returns the last point and the relative change", () => {
    expect(latestNetWorth(points)?.as_of).toBe("2026-01-03");
    expect(latestNetWorth([])).toBeNull();
    const change = periodChange(netWorthSeries(points, "DKK"));
    expect(change).toBeCloseTo(0.1);
  });

  it("returns null change for empty or zero-base series", () => {
    expect(periodChange([])).toBeNull();
    expect(periodChange([["2026-01-01", 0]])).toBeNull();
  });
});

describe("allocationData", () => {
  it("sorts by EUR balance and keeps the weight", () => {
    const data = allocationData([
      { label: "checking", balance_eur: "100.0", balance_dkk: "746.0", weight_eur: "0.2" },
      { label: "pension", balance_eur: "400.0", balance_dkk: "2984.0", weight_eur: "0.8" },
      { label: "broken", balance_eur: null, balance_dkk: null, weight_eur: null },
    ]);
    expect(data.map((datum) => datum.name)).toEqual(["pension", "checking"]);
    expect(data[0]?.share).toBeCloseTo(0.8);
  });
});

describe("monthlyCashflow", () => {
  it("aggregates account-day points into sorted months", () => {
    const base: Omit<CashflowPoint, "as_of" | "inflow_eur" | "outflow_eur" | "net_eur"> = {
      account_currency: "DKK",
      account_id: "a",
      entity_id: "e",
      inflow_acct_ccy: "0",
      inflow_dkk: "0",
      net_acct_ccy: "0",
      net_dkk: "0",
      outflow_acct_ccy: "0",
      outflow_dkk: "0",
    };
    const months = monthlyCashflow([
      { ...base, as_of: "2026-02-10", inflow_eur: "50.0", outflow_eur: "20.0", net_eur: "30.0" },
      { ...base, as_of: "2026-01-05", inflow_eur: "100.0", outflow_eur: "40.0", net_eur: "60.0" },
      { ...base, as_of: "2026-01-20", inflow_eur: "10.0", outflow_eur: "5.0", net_eur: "5.0" },
    ]);
    expect(months.map((month) => month.month)).toEqual(["2026-01", "2026-02"]);
    expect(months[0]?.inflowEur).toBeCloseTo(110);
    expect(months[0]?.netEur).toBeCloseTo(65);
  });
});

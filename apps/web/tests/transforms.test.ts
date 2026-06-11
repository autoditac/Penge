import { describe, expect, it } from "vitest";

import type {
  AccountSummary,
  CashflowPoint,
  NetWorthPoint,
  NetWorthTotalPoint,
} from "../src/api/schemas";
import {
  allocationData,
  allocationDrift,
  drawdownSeries,
  kindWeightHistory,
  latestNetWorth,
  liquidShare,
  maxDrawdown,
  monthOverMonthChange,
  monthlyCashflow,
  netWorthSeries,
  perAccountSeries,
  perKindSeries,
  periodChange,
  savingsRateSeries,
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

describe("drawdownSeries / maxDrawdown", () => {
  it("measures the distance from the running peak", () => {
    const series: [string, number][] = [
      ["2026-01-01", 100],
      ["2026-01-02", 120],
      ["2026-01-03", 90],
      ["2026-01-04", 130],
    ];
    const drawdown = drawdownSeries(series);
    expect(drawdown[0]?.[1]).toBeCloseTo(0);
    expect(drawdown[1]?.[1]).toBeCloseTo(0);
    expect(drawdown[2]?.[1]).toBeCloseTo(-0.25);
    expect(drawdown[3]?.[1]).toBeCloseTo(0);
    expect(maxDrawdown(series)).toBeCloseTo(-0.25);
  });

  it("handles empty and non-positive-peak series", () => {
    expect(maxDrawdown([])).toBeNull();
    expect(drawdownSeries([["2026-01-01", -5]])[0]?.[1]).toBe(0);
  });
});

describe("savingsRateSeries", () => {
  const months = [
    { month: "2026-01", inflowEur: 1000, outflowEur: 600, netEur: 400 },
    { month: "2026-02", inflowEur: 1000, outflowEur: 900, netEur: 100 },
    { month: "2026-03", inflowEur: 0, outflowEur: 500, netEur: -500 },
  ];

  it("computes a rolling (inflow − outflow) / inflow rate", () => {
    const rates = savingsRateSeries(months, 2);
    expect(rates[0]?.rate).toBeCloseTo(0.4);
    expect(rates[1]?.rate).toBeCloseTo((2000 - 1500) / 2000);
    expect(rates[2]?.rate).toBeCloseTo((1000 - 1400) / 1000);
  });

  it("returns null when the window has no inflow", () => {
    expect(savingsRateSeries([months[2] ?? months[0]!], 1)[0]?.rate).toBeNull();
  });
});

const drillAccounts: AccountSummary[] = [
  {
    account_id: "a1",
    currency: "EUR",
    entity_id: "e1",
    entity_name: "Person A",
    iban_masked: "****1",
    kind: "checking",
    name: "Giro",
    provider: "gls",
  },
  {
    account_id: "a2",
    currency: "DKK",
    entity_id: "e2",
    entity_name: "Person B",
    iban_masked: "****2",
    kind: "investment",
    name: "Depot",
    provider: "nordnet",
  },
];

function netWorthPoint(accountId: string, asOf: string, eur: string | null): NetWorthPoint {
  return {
    account_currency: "EUR",
    account_id: accountId,
    as_of: asOf,
    balance_acct_ccy: eur ?? "0",
    balance_dkk: null,
    balance_eur: eur,
    entity_id: "e1",
  };
}

const drillPoints: NetWorthPoint[] = [
  netWorthPoint("a1", "2026-01-01", "100.0"),
  netWorthPoint("a2", "2026-01-01", "300.0"),
  netWorthPoint("a1", "2026-01-02", "110.0"),
  netWorthPoint("a2", "2026-01-02", "290.0"),
  netWorthPoint("a2", "2026-01-03", null),
];

describe("perAccountSeries / perKindSeries", () => {
  it("builds one labelled EUR series per account, sorted by label", () => {
    const series = perAccountSeries(drillPoints, drillAccounts);
    expect(series.map((entry) => entry.label)).toEqual(["Depot", "Giro"]);
    expect(series[1]?.series).toEqual([
      ["2026-01-01", 100],
      ["2026-01-02", 110],
    ]);
  });

  it("sums balances per kind and skips null EUR legs", () => {
    const series = perKindSeries(drillPoints, drillAccounts);
    expect(series.map((entry) => entry.label)).toEqual(["checking", "investment"]);
    expect(series[1]?.series).toEqual([
      ["2026-01-01", 300],
      ["2026-01-02", 290],
    ]);
  });

  it("falls back to the account id / unknown kind when unmapped", () => {
    const series = perAccountSeries([netWorthPoint("ghost", "2026-01-01", "5.0")], []);
    expect(series[0]?.label).toBe("ghost");
    const kinds = perKindSeries([netWorthPoint("ghost", "2026-01-01", "5.0")], []);
    expect(kinds[0]?.label).toBe("unknown");
  });
});

describe("kindWeightHistory / allocationDrift", () => {
  it("computes per-date kind weights that sum to one", () => {
    const history = kindWeightHistory(drillPoints, drillAccounts);
    expect(history.dates).toEqual(["2026-01-01", "2026-01-02", "2026-01-03"]);
    expect(history.kinds).toEqual(["checking", "investment"]);
    expect(history.weights[0]?.[0]).toBeCloseTo(0.25);
    expect(history.weights[1]?.[0]).toBeCloseTo(0.75);
    expect(history.weights[0]?.[1]).toBeCloseTo(110 / 400);
  });

  it("compares the latest weights against targets", () => {
    const history = kindWeightHistory(drillPoints.slice(0, 4), drillAccounts);
    const drift = allocationDrift(history, { checking: 0.5, pension: 0.2 });
    const checking = drift.find((entry) => entry.kind === "checking");
    expect(checking?.current).toBeCloseTo(110 / 400);
    expect(checking?.drift).toBeCloseTo(110 / 400 - 0.5);
    const pension = drift.find((entry) => entry.kind === "pension");
    expect(pension?.current).toBe(0);
    expect(pension?.target).toBeCloseTo(0.2);
  });

  it("returns no drift entries for an empty history", () => {
    expect(allocationDrift({ dates: [], kinds: [], weights: [] }, { checking: 1 })).toEqual([]);
  });
});

describe("monthOverMonthChange", () => {
  it("compares the latest value with the previous month end", () => {
    const change = monthOverMonthChange([
      ["2026-01-30", 100],
      ["2026-01-31", 110],
      ["2026-02-15", 121],
    ]);
    expect(change).toBeCloseTo(0.1);
  });

  it("returns null without a previous-month reference", () => {
    expect(monthOverMonthChange([])).toBeNull();
    expect(monthOverMonthChange([["2026-02-01", 100]])).toBeNull();
  });
});

describe("liquidShare", () => {
  it("sums liquid kinds over the EUR total", () => {
    const share = liquidShare(
      [
        { label: "checking", balance_eur: "100.0", balance_dkk: null, weight_eur: null },
        { label: "pension", balance_eur: "300.0", balance_dkk: null, weight_eur: null },
      ],
      new Set(["checking"]),
    );
    expect(share).toBeCloseTo(0.25);
  });

  it("returns null when the total is not positive", () => {
    expect(liquidShare([], new Set(["checking"]))).toBeNull();
  });
});

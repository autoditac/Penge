import { describe, expect, it } from "vitest";

import type { FeeYearRow, NetWorthTotalPoint, ReturnsPoint } from "../src/api/schemas";
import {
  benchmarkIndexSeries,
  contributionGrowthSeries,
  feeDragByYear,
  twrIndexByKey,
  twrIndexSeries,
} from "../src/transforms";

function point(overrides: Partial<ReturnsPoint> & { as_of: string }): ReturnsPoint {
  return {
    begin_mv_dkk: null,
    begin_mv_eur: null,
    end_mv_dkk: null,
    end_mv_eur: null,
    net_flow_dkk: null,
    net_flow_eur: null,
    return_factor_dkk: null,
    return_factor_eur: null,
    scope: "household",
    scope_key: "household",
    ...overrides,
  };
}

describe("twrIndexSeries", () => {
  it("chain-links daily factors into an index starting at 100", () => {
    const series = twrIndexSeries(
      [
        point({ as_of: "2026-01-01", return_factor_eur: "1.0100000000" }),
        point({ as_of: "2026-01-02", return_factor_eur: "1.0000000000" }),
        point({ as_of: "2026-01-03", return_factor_eur: "1.0200000000" }),
      ],
      "EUR",
    );
    expect(series.map(([date]) => date)).toEqual(["2026-01-01", "2026-01-02", "2026-01-03"]);
    expect(series[0]?.[1]).toBeCloseTo(101, 8);
    expect(series[1]?.[1]).toBeCloseTo(101, 8);
    expect(series[2]?.[1]).toBeCloseTo(103.02, 8);
  });

  it("carries the level forward over null factors (dormant days)", () => {
    const series = twrIndexSeries(
      [
        point({ as_of: "2026-01-01", return_factor_eur: "1.1000000000" }),
        point({ as_of: "2026-01-02", return_factor_eur: null }),
        point({ as_of: "2026-01-03", return_factor_eur: "1.1000000000" }),
      ],
      "EUR",
    );
    expect(series[1]?.[1]).toBeCloseTo(110, 8);
    expect(series[2]?.[1]).toBeCloseTo(121, 8);
  });

  it("reads the DKK leg when asked", () => {
    const series = twrIndexSeries(
      [point({ as_of: "2026-01-01", return_factor_dkk: "1.0500000000" })],
      "DKK",
    );
    expect(series[0]?.[1]).toBeCloseTo(105, 8);
  });
});

describe("twrIndexByKey", () => {
  it("groups by scope key and applies the label resolver, sorted by label", () => {
    const points = [
      point({
        as_of: "2026-01-01",
        scope: "account",
        scope_key: "b",
        return_factor_eur: "1.0100000000",
      }),
      point({
        as_of: "2026-01-01",
        scope: "account",
        scope_key: "a",
        return_factor_eur: "1.0200000000",
      }),
      point({
        as_of: "2026-01-02",
        scope: "account",
        scope_key: "b",
        return_factor_eur: "1.0100000000",
      }),
    ];
    const lines = twrIndexByKey(points, "EUR", (key) => (key === "a" ? "Zeta" : "Alpha"));
    expect(lines.map((line) => line.label)).toEqual(["Alpha", "Zeta"]);
    expect(lines[0]?.series).toHaveLength(2);
    expect(lines[0]?.series[1]?.[1]).toBeCloseTo(102.01, 6);
    expect(lines[1]?.series).toHaveLength(1);
  });
});

describe("benchmarkIndexSeries", () => {
  it("normalizes closes to base 100 at the first point", () => {
    const series = benchmarkIndexSeries([
      { as_of: "2026-01-01", close: "50.0000" },
      { as_of: "2026-01-02", close: "55.0000" },
      { as_of: "2026-01-03", close: "45.0000" },
    ]);
    expect(series).toEqual([
      ["2026-01-01", 100],
      ["2026-01-02", 110.00000000000001],
      ["2026-01-03", 90],
    ]);
  });

  it("returns empty for no points or a zero first close", () => {
    expect(benchmarkIndexSeries([])).toEqual([]);
    expect(benchmarkIndexSeries([{ as_of: "2026-01-01", close: "0.0000" }])).toEqual([]);
  });
});

describe("contributionGrowthSeries", () => {
  it("splits value change into cumulative flows and growth", () => {
    const series = contributionGrowthSeries(
      [
        point({
          as_of: "2026-01-01",
          begin_mv_eur: "1000.0000",
          end_mv_eur: "1110.0000",
          net_flow_eur: "100.0000",
        }),
        point({
          as_of: "2026-01-02",
          begin_mv_eur: "1110.0000",
          end_mv_eur: "1100.0000",
          net_flow_eur: "0.0000",
        }),
      ],
      "EUR",
    );
    expect(series).toHaveLength(2);
    expect(series[0]?.flowsCum).toBeCloseTo(100, 8);
    expect(series[0]?.growthCum).toBeCloseTo(10, 8);
    expect(series[1]?.flowsCum).toBeCloseTo(100, 8);
    expect(series[1]?.growthCum).toBeCloseTo(0, 8);
  });

  it("skips days without begin or end value and treats null flow as zero", () => {
    const series = contributionGrowthSeries(
      [
        point({ as_of: "2026-01-01", begin_mv_eur: null, end_mv_eur: "100.0000" }),
        point({
          as_of: "2026-01-02",
          begin_mv_eur: "100.0000",
          end_mv_eur: "105.0000",
          net_flow_eur: null,
        }),
      ],
      "EUR",
    );
    expect(series).toHaveLength(1);
    expect(series[0]?.growthCum).toBeCloseTo(5, 8);
    expect(series[0]?.flowsCum).toBe(0);
  });
});

describe("feeDragByYear", () => {
  const netWorth: NetWorthTotalPoint[] = [
    { as_of: "2025-06-01", balance_eur: "10000.0000", balance_dkk: "74600.0000" },
    { as_of: "2025-12-01", balance_eur: "12000.0000", balance_dkk: "89520.0000" },
  ];

  it("sums fees per year across accounts and computes drag vs average net worth", () => {
    const rows: FeeYearRow[] = [
      { account_id: "a1", year: 2025, fees_eur: "30.0000", fees_dkk: "223.8000" },
      { account_id: "a2", year: 2025, fees_eur: "25.0000", fees_dkk: "186.5000" },
    ];
    const result = feeDragByYear(rows, netWorth);
    expect(result).toHaveLength(1);
    expect(result[0]?.year).toBe(2025);
    expect(result[0]?.feesEur).toBeCloseTo(55, 8);
    expect(result[0]?.feesDkk).toBeCloseTo(410.3, 8);
    // average net worth = 11000 EUR → 55 / 11000 = 0.5%
    expect(result[0]?.dragShare).toBeCloseTo(0.005, 8);
  });

  it("returns null drag when the year has no net-worth observations", () => {
    const rows: FeeYearRow[] = [
      { account_id: "a1", year: 2020, fees_eur: "10.0000", fees_dkk: "74.6000" },
    ];
    const result = feeDragByYear(rows, netWorth);
    expect(result[0]?.dragShare).toBeNull();
  });

  it("sorts rows by year ascending", () => {
    const rows: FeeYearRow[] = [
      { account_id: "a1", year: 2026, fees_eur: "1.0000", fees_dkk: null },
      { account_id: "a1", year: 2024, fees_eur: "2.0000", fees_dkk: null },
    ];
    expect(feeDragByYear(rows, netWorth).map((row) => row.year)).toEqual([2024, 2026]);
  });
});

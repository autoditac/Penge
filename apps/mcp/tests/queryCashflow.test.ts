import { describe, expect, it } from "vitest";

import {
  queryCashflowTool,
  type CashflowQueryRunner,
  type QueryCashflowInput,
} from "../src/tools/queryCashflow.js";

interface CapturedCall {
  sql: string;
  params: ReadonlyArray<unknown>;
}

function makeRunner<R extends Record<string, unknown>>(
  rows: R[],
): CashflowQueryRunner & { calls: CapturedCall[] } {
  const calls: CapturedCall[] = [];
  return {
    calls,
    async query(sql, params) {
      calls.push({ sql, params });
      return { rows: rows as never };
    },
  };
}

const ctx = { serverName: "test", serverVersion: "0.0.0-test" };

const baseArgs: QueryCashflowInput = {
  date_range: { from: "2024-01-01", to: "2024-01-31" },
  granularity: "month",
};

describe("query_cashflow — schema validation", () => {
  it("accepts a well-formed payload (no currency)", () => {
    const tool = queryCashflowTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse(baseArgs)).not.toThrow();
  });

  it("accepts an explicit currency", () => {
    const tool = queryCashflowTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, currency: "DKK" })).not.toThrow();
  });

  it("rejects non-ISO dates", () => {
    const tool = queryCashflowTool({ runner: makeRunner([]) });
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, date_range: { from: "2024/01/01", to: "2024-01-31" } }),
    ).toThrow();
  });

  it("rejects from > to", () => {
    const tool = queryCashflowTool({ runner: makeRunner([]) });
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, date_range: { from: "2024-02-01", to: "2024-01-31" } }),
    ).toThrow();
  });

  it("rejects calendar-impossible dates that match the YYYY-MM-DD shape", () => {
    const tool = queryCashflowTool({ runner: makeRunner([]) });
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, date_range: { from: "2024-13-40", to: "2024-13-41" } }),
    ).toThrow();
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, date_range: { from: "2024-02-30", to: "2024-03-01" } }),
    ).toThrow();
  });

  it("rejects unknown currency", () => {
    const tool = queryCashflowTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, currency: "USD" })).toThrow();
  });

  it("rejects unknown granularity", () => {
    const tool = queryCashflowTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, granularity: "quarter" })).toThrow();
  });

  it("rejects unknown extra keys (strict)", () => {
    const tool = queryCashflowTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, extra: 1 })).toThrow();
  });
});

describe("query_cashflow — SQL shape", () => {
  it("uses *_eur columns when currency=EUR (default) and parameterizes inputs", async () => {
    const runner = makeRunner([]);
    const tool = queryCashflowTool({ runner });
    await tool.handler(baseArgs, ctx);
    expect(runner.calls).toHaveLength(1);
    const sql = runner.calls[0]!.sql;
    expect(sql).toMatch(/m\.inflow_eur/);
    expect(sql).toMatch(/m\.outflow_eur/);
    expect(sql).toMatch(/m\.net_eur/);
    expect(sql).not.toMatch(/inflow_dkk|outflow_dkk|net_dkk/);
    expect(runner.calls[0]!.params).toEqual(["2024-01-01", "2024-01-31", "month"]);
  });

  it("uses *_dkk columns when currency=DKK", async () => {
    const runner = makeRunner([]);
    const tool = queryCashflowTool({ runner });
    await tool.handler({ ...baseArgs, currency: "DKK" }, ctx);
    const sql = runner.calls[0]!.sql;
    expect(sql).toMatch(/m\.inflow_dkk/);
    expect(sql).toMatch(/m\.outflow_dkk/);
    expect(sql).toMatch(/m\.net_dkk/);
    expect(sql).not.toMatch(/inflow_eur|outflow_eur|net_eur/);
  });

  it("passes granularity as a parameter, not concatenated into SQL", async () => {
    const runner = makeRunner([]);
    const tool = queryCashflowTool({ runner });
    for (const granularity of ["day", "week", "month", "year"] as const) {
      runner.calls.length = 0;
      await tool.handler({ ...baseArgs, granularity }, ctx);
      const sql = runner.calls[0]!.sql;
      // Granularity must travel as $3, never embedded in the SQL text.
      expect(sql).toMatch(/date_trunc\(\$3::text/);
      expect(sql).not.toMatch(new RegExp(`date_trunc\\('${granularity}'`));
      expect(runner.calls[0]!.params[2]).toBe(granularity);
    }
  });

  it("clips period bounds to the requested date_range with GREATEST/LEAST", async () => {
    const runner = makeRunner([]);
    const tool = queryCashflowTool({ runner });
    await tool.handler(baseArgs, ctx);
    const sql = runner.calls[0]!.sql;
    expect(sql).toMatch(/GREATEST\(bucket_start, \$1::date\)/);
    expect(sql).toMatch(/LEAST\(bucket_end, \$2::date\)/);
  });

  it("respects martTable override and uses it verbatim", async () => {
    const runner = makeRunner([]);
    const tool = queryCashflowTool({
      runner,
      martTable: "custom_marts.mart_cashflow_daily",
    });
    await tool.handler(baseArgs, ctx);
    expect(runner.calls[0]!.sql).toMatch(/custom_marts\.mart_cashflow_daily/);
  });

  it("rejects martTable overrides that are not safe schema.table identifiers", () => {
    const runner = makeRunner([]);
    expect(() => queryCashflowTool({ runner, martTable: "x; DROP TABLE foo --" })).toThrow(
      /martTable/,
    );
    expect(() =>
      queryCashflowTool({ runner, martTable: "analytics_marts.mart WHERE 1=1" }),
    ).toThrow(/martTable/);
    expect(() => queryCashflowTool({ runner, martTable: "no_schema_only" })).toThrow(/martTable/);
    expect(() => queryCashflowTool({ runner, martTable: "schema.table; --" })).toThrow(/martTable/);
  });
});

describe("query_cashflow — output shape & rollup correctness", () => {
  it("aggregates rows into the wire schema and echoes default currency", async () => {
    const runner = makeRunner([
      {
        period_start: "2024-01-01",
        period_end: "2024-01-31",
        inflow: "1500.50",
        outflow: "500.25",
        net: "1000.25",
      },
    ]);
    const tool = queryCashflowTool({ runner });
    const result = await tool.handler(baseArgs, ctx);
    const validated = tool.outputSchema.parse(result);
    expect(validated).toEqual([
      {
        period_start: "2024-01-01",
        period_end: "2024-01-31",
        currency: "EUR",
        inflow: 1500.5,
        outflow: 500.25,
        net: 1000.25,
      },
    ]);
  });

  it("treats null aggregated values as 0", async () => {
    const runner = makeRunner([
      {
        period_start: "2024-01-01",
        period_end: "2024-01-01",
        inflow: null,
        outflow: null,
        net: null,
      },
    ]);
    const tool = queryCashflowTool({ runner });
    const [row] = await tool.handler({ ...baseArgs, granularity: "day" }, ctx);
    expect(row).toEqual({
      period_start: "2024-01-01",
      period_end: "2024-01-01",
      currency: "EUR",
      inflow: 0,
      outflow: 0,
      net: 0,
    });
  });

  it("formats Date instances back to ISO YYYY-MM-DD", async () => {
    const runner = makeRunner([
      {
        period_start: new Date("2024-02-05T00:00:00Z"),
        period_end: new Date("2024-02-11T00:00:00Z"),
        inflow: 100,
        outflow: 40,
        net: 60,
      },
    ]);
    const tool = queryCashflowTool({ runner });
    const [row] = await tool.handler({ ...baseArgs, granularity: "week" }, ctx);
    expect(row?.period_start).toBe("2024-02-05");
    expect(row?.period_end).toBe("2024-02-11");
  });

  it("never leaks raw transaction-shaped fields", async () => {
    const runner = makeRunner([
      {
        period_start: "2024-01-01",
        period_end: "2024-01-07",
        inflow: 100,
        outflow: 25,
        net: 75,
        // simulate a careless query that returned extra columns; the
        // wire schema must drop them.
        account_iban: "DE89...",
        transaction_id: "tx-1",
      },
    ]);
    const tool = queryCashflowTool({ runner });
    const result = await tool.handler({ ...baseArgs, granularity: "week" }, ctx);
    const validated = tool.outputSchema.parse(result);
    expect(Object.keys(validated[0]!).sort()).toEqual(
      ["period_start", "period_end", "currency", "inflow", "outflow", "net"].sort(),
    );
  });

  it("rollup correctness: weekly sums match the per-day fixture", async () => {
    // Simulate what Postgres returns for a weekly rollup of three days
    // worth of cashflow. The mart had:
    //   2024-01-01: inflow 100, outflow 30, net 70
    //   2024-01-02: inflow 200, outflow 50, net 150
    //   2024-01-03: inflow 50,  outflow 0,  net 50
    // All in the same ISO week → one bucket.
    const runner = makeRunner([
      {
        period_start: "2024-01-01",
        period_end: "2024-01-07",
        inflow: 350,
        outflow: 80,
        net: 270,
      },
    ]);
    const tool = queryCashflowTool({ runner });
    const [row] = await tool.handler(
      {
        date_range: { from: "2024-01-01", to: "2024-01-07" },
        granularity: "week",
      },
      ctx,
    );
    expect(row?.inflow).toBe(350);
    expect(row?.outflow).toBe(80);
    expect(row?.net).toBe(270);
    // Sanity: net = inflow - outflow.
    expect(row!.inflow - row!.outflow).toBeCloseTo(row!.net, 6);
  });

  it("rollup correctness: monthly fixture sums and orders by period_start", async () => {
    const runner = makeRunner([
      {
        period_start: "2024-01-01",
        period_end: "2024-01-31",
        inflow: 1000,
        outflow: 400,
        net: 600,
      },
      { period_start: "2024-02-01", period_end: "2024-02-29", inflow: 800, outflow: 600, net: 200 },
      { period_start: "2024-03-01", period_end: "2024-03-31", inflow: 500, outflow: 100, net: 400 },
    ]);
    const tool = queryCashflowTool({ runner });
    const result = await tool.handler(
      {
        date_range: { from: "2024-01-01", to: "2024-03-31" },
        granularity: "month",
        currency: "DKK",
      },
      ctx,
    );
    const validated = tool.outputSchema.parse(result);
    expect(validated).toHaveLength(3);
    expect(validated.map((r) => r.period_start)).toEqual([
      "2024-01-01",
      "2024-02-01",
      "2024-03-01",
    ]);
    expect(validated.every((r) => r.currency === "DKK")).toBe(true);
    const totalNet = validated.reduce((acc, r) => acc + r.net, 0);
    expect(totalNet).toBe(1200);
  });
});

describe("query_cashflow — error handling", () => {
  it("propagates underlying query errors", async () => {
    const runner: CashflowQueryRunner = {
      async query() {
        throw new Error("relation does not exist");
      },
    };
    const tool = queryCashflowTool({ runner });
    await expect(tool.handler(baseArgs, ctx)).rejects.toThrow(/relation does not exist/);
  });
});

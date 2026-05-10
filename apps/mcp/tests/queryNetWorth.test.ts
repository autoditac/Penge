import { describe, expect, it } from "vitest";

import {
  queryNetWorthTool,
  type NetWorthQueryRunner,
  type QueryNetWorthInput,
} from "../src/tools/queryNetWorth.js";

interface CapturedCall {
  sql: string;
  params: ReadonlyArray<unknown>;
}

function makeRunner<R extends Record<string, unknown>>(
  rows: R[],
): NetWorthQueryRunner & { calls: CapturedCall[] } {
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

const baseArgs: QueryNetWorthInput = {
  date_range: { from: "2024-01-01", to: "2024-01-31" },
  currency: "EUR",
  breakdown_by: "none",
};

describe("query_net_worth — schema validation", () => {
  it("accepts a well-formed payload", () => {
    const runner = makeRunner([]);
    const tool = queryNetWorthTool({ runner });
    expect(() => tool.inputSchema.parse(baseArgs)).not.toThrow();
  });

  it("rejects non-ISO dates", () => {
    const tool = queryNetWorthTool({ runner: makeRunner([]) });
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, date_range: { from: "2024/01/01", to: "2024-01-31" } }),
    ).toThrow();
  });

  it("rejects from > to", () => {
    const tool = queryNetWorthTool({ runner: makeRunner([]) });
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, date_range: { from: "2024-02-01", to: "2024-01-31" } }),
    ).toThrow();
  });

  it("rejects calendar-impossible dates that match the YYYY-MM-DD shape", () => {
    const tool = queryNetWorthTool({ runner: makeRunner([]) });
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, date_range: { from: "2024-13-40", to: "2024-13-41" } }),
    ).toThrow();
    expect(() =>
      tool.inputSchema.parse({ ...baseArgs, date_range: { from: "2024-02-30", to: "2024-03-01" } }),
    ).toThrow();
  });

  it("rejects unknown currency", () => {
    const tool = queryNetWorthTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, currency: "USD" })).toThrow();
  });

  it("rejects unknown breakdown_by", () => {
    const tool = queryNetWorthTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, breakdown_by: "instrument" })).toThrow();
  });

  it("rejects unknown extra keys (strict)", () => {
    const tool = queryNetWorthTool({ runner: makeRunner([]) });
    expect(() => tool.inputSchema.parse({ ...baseArgs, extra: 1 })).toThrow();
  });
});

describe("query_net_worth — SQL shape", () => {
  it("uses balance_eur for EUR and parameterizes the date range", async () => {
    const runner = makeRunner([]);
    const tool = queryNetWorthTool({ runner });
    await tool.handler({ ...baseArgs, currency: "EUR", breakdown_by: "none" }, ctx);
    expect(runner.calls).toHaveLength(1);
    expect(runner.calls[0]!.sql).toMatch(/balance_eur/);
    expect(runner.calls[0]!.sql).not.toMatch(/balance_dkk/);
    expect(runner.calls[0]!.params).toEqual(["2024-01-01", "2024-01-31"]);
  });

  it("uses balance_dkk for DKK", async () => {
    const runner = makeRunner([]);
    const tool = queryNetWorthTool({ runner });
    await tool.handler({ ...baseArgs, currency: "DKK" }, ctx);
    expect(runner.calls[0]!.sql).toMatch(/balance_dkk/);
    expect(runner.calls[0]!.sql).not.toMatch(/balance_eur/);
  });

  it("groups by account_id when breakdown_by=account", async () => {
    const runner = makeRunner([]);
    const tool = queryNetWorthTool({ runner });
    await tool.handler({ ...baseArgs, breakdown_by: "account" }, ctx);
    expect(runner.calls[0]!.sql).toMatch(/GROUP BY m\.as_of, m\.account_id/);
    expect(runner.calls[0]!.sql).not.toMatch(/JOIN/);
  });

  it("joins account.kind for breakdown_by=asset_class", async () => {
    const runner = makeRunner([]);
    const tool = queryNetWorthTool({ runner });
    await tool.handler({ ...baseArgs, breakdown_by: "asset_class" }, ctx);
    expect(runner.calls[0]!.sql).toMatch(/INNER JOIN .*account.* AS a/);
    expect(runner.calls[0]!.sql).toMatch(/a\.kind/);
  });

  it("respects martTable / accountTable overrides", async () => {
    const runner = makeRunner([]);
    const tool = queryNetWorthTool({
      runner,
      martTable: "custom_marts.mart_net_worth_daily",
      accountTable: "custom.account",
    });
    await tool.handler({ ...baseArgs, breakdown_by: "asset_class" }, ctx);
    expect(runner.calls[0]!.sql).toMatch(/custom_marts\.mart_net_worth_daily/);
    expect(runner.calls[0]!.sql).toMatch(/custom\.account/);
  });

  it("rejects table overrides that are not safe schema.table identifiers", () => {
    const runner = makeRunner([]);
    expect(() => queryNetWorthTool({ runner, martTable: "x; DROP TABLE foo --" })).toThrow(
      /martTable/,
    );
    expect(() => queryNetWorthTool({ runner, accountTable: "public.account WHERE 1=1" })).toThrow(
      /accountTable/,
    );
    expect(() => queryNetWorthTool({ runner, martTable: "no_schema_only" })).toThrow(/martTable/);
  });
});

describe("query_net_worth — output shape", () => {
  it("aggregates rows into the wire schema with no breakdown_key when breakdown_by=none", async () => {
    const runner = makeRunner([
      { date: "2024-01-01", breakdown_key: null, value: "1000.50" },
      { date: new Date("2024-01-02T00:00:00Z"), breakdown_key: null, value: 2000.25 },
    ]);
    const tool = queryNetWorthTool({ runner });
    const result = await tool.handler(baseArgs, ctx);
    const validated = tool.outputSchema.parse(result);
    expect(validated).toEqual([
      { date: "2024-01-01", currency: "EUR", value: 1000.5 },
      { date: "2024-01-02", currency: "EUR", value: 2000.25 },
    ]);
  });

  it("includes breakdown_key when breakdown_by != none", async () => {
    const runner = makeRunner([
      { date: "2024-01-01", breakdown_key: "bank", value: 500 },
      { date: "2024-01-01", breakdown_key: "brokerage", value: 1500 },
    ]);
    const tool = queryNetWorthTool({ runner });
    const result = await tool.handler({ ...baseArgs, breakdown_by: "asset_class" }, ctx);
    const validated = tool.outputSchema.parse(result);
    expect(validated).toEqual([
      { date: "2024-01-01", currency: "EUR", breakdown_key: "bank", value: 500 },
      { date: "2024-01-01", currency: "EUR", breakdown_key: "brokerage", value: 1500 },
    ]);
  });

  it("treats null aggregated value as 0", async () => {
    const runner = makeRunner([{ date: "2024-01-01", breakdown_key: null, value: null }]);
    const tool = queryNetWorthTool({ runner });
    const [row] = await tool.handler(baseArgs, ctx);
    expect(row?.value).toBe(0);
  });

  it("never leaks raw transaction-shaped fields", async () => {
    const runner = makeRunner([
      {
        date: "2024-01-01",
        breakdown_key: "acct-uuid-1",
        value: 100,
        // simulate a careless query that returned extra columns; the
        // wire schema must drop them
        account_iban: "DE89...",
        transaction_id: "tx-1",
      },
    ]);
    const tool = queryNetWorthTool({ runner });
    const result = await tool.handler({ ...baseArgs, breakdown_by: "account" }, ctx);
    const validated = tool.outputSchema.parse(result);
    expect(Object.keys(validated[0]!).sort()).toEqual(
      ["date", "currency", "value", "breakdown_key"].sort(),
    );
  });
});

describe("query_net_worth — error handling", () => {
  it("propagates underlying query errors", async () => {
    const runner: NetWorthQueryRunner = {
      async query() {
        throw new Error("relation does not exist");
      },
    };
    const tool = queryNetWorthTool({ runner });
    await expect(tool.handler(baseArgs, ctx)).rejects.toThrow(/relation does not exist/);
  });
});

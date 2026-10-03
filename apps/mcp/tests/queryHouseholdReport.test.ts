import { describe, expect, it } from "vitest";

import {
  queryHouseholdReportTool,
  type HouseholdReportQueryRunner,
} from "../src/tools/queryHouseholdReport.js";

class FakeRunner implements HouseholdReportQueryRunner {
  readonly calls: Array<{ sql: string; params: ReadonlyArray<unknown> }> = [];

  constructor(private readonly rows: Array<Record<string, unknown>>) {}

  async query<R extends Record<string, unknown>>(
    sql: string,
    params: ReadonlyArray<unknown>,
  ): Promise<{ rows: R[] }> {
    this.calls.push({ sql, params });
    if (sql.includes("CHECK_ACCOUNTS")) return { rows: [{ count: 0 } as R] };
    if (sql.includes("CHECK_CATEGORY")) return { rows: [{ found: true } as R] };
    return { rows: this.rows as R[] };
  }
}

function martRow(
  asOf: string,
  treatment: "income" | "expense" | "refund" | "unclassified",
  amountEur: string,
  amountDkk: string,
  missingEur = 0,
  missingDkk = 0,
): Record<string, unknown> {
  return {
    as_of: asOf,
    treatment,
    known_allocation_amount_eur: amountEur,
    known_allocation_amount_dkk: amountDkk,
    missing_fx_count_eur: missingEur,
    missing_fx_count_dkk: missingDkk,
  };
}

describe("query_household_report", () => {
  it("returns exact bank-ledger summaries, previous comparison, and month trend", async () => {
    const runner = new FakeRunner([
      martRow("2025-06-12", "expense", "-20.00000000", "-149.20000000"),
      martRow("2025-07-05", "expense", "-12.50000000", "-93.25000000"),
      martRow("2025-07-06", "refund", "2.50000000", "18.65000000"),
      martRow("2025-07-10", "income", "100.00000000", "746.00000000"),
      martRow("2025-07-12", "unclassified", "-1.25000000", "-9.32500000"),
    ]);
    const tool = queryHouseholdReportTool({ runner });
    const result = await tool.handler({
      date_range: { from: "2025-07-01", to: "2025-07-31" },
      granularity: "month",
    });

    expect(result.current.totals.gross_expenses.eur).toEqual({
      amount: "13.75",
      known_subtotal: "13.75",
      complete: true,
      missing_count: 0,
    });
    expect(result.current.totals.refunds.eur.amount).toBe("2.5");
    expect(result.current.totals.net_expenses.eur.amount).toBe("11.25");
    expect(result.current.totals.surplus.eur.amount).toBe("88.75");
    expect(result.previous.totals.gross_expenses.eur.amount).toBe("20");
    expect(result.change.gross_expenses.eur.amount).toBe("-6.25");
    expect(result.trend).toHaveLength(1);
    expect(result.trend[0]?.period_start).toBe("2025-07-01");
    expect(runner.calls.at(-1)?.sql).toContain("mart_household_report_daily");
  });

  it("encodes missing FX as null while retaining the exact known subtotal", async () => {
    const runner = new FakeRunner([martRow("2025-07-05", "expense", "0", "-93.25000000", 1, 0)]);
    const tool = queryHouseholdReportTool({ runner });
    const result = await tool.handler({
      date_range: { from: "2025-07-01", to: "2025-07-31" },
      granularity: "month",
    });

    expect(result.current.totals.gross_expenses.eur).toEqual({
      amount: null,
      known_subtotal: "0",
      complete: false,
      missing_count: 1,
    });
  });

  it("rejects non-checking account filters and exposes only aggregate fields", async () => {
    const runner = new FakeRunner([]);
    const tool = queryHouseholdReportTool({ runner });
    const accountId = "550e8400-e29b-41d4-a716-446655440000";

    await expect(
      tool.handler({
        date_range: { from: "2025-07-01", to: "2025-07-31" },
        granularity: "month",
        account_ids: [accountId],
      }),
    ).rejects.toThrow("account_ids must contain only checking accounts");
    expect(runner.calls).toHaveLength(1);
    expect(runner.calls[0]?.sql).toContain("kind = 'checking'");
  });
});

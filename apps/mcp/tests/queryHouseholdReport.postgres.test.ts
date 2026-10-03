import { describe, expect, it } from "vitest";

import { connect } from "../src/db.js";
import { queryHouseholdReportTool } from "../src/tools/queryHouseholdReport.js";

const enabled = process.env.PENGE_MCP_REPORT_PG_TEST === "1";

describe.skipIf(!enabled)("query_household_report on disposable PostgreSQL", () => {
  it("executes every granularity with real positional parameters and synthetic marts", async () => {
    const rawUrl = process.env.PENGE_TEST_DATABASE_URL;
    if (!rawUrl || process.env.PENGE_ALLOW_DESTRUCTIVE_TEST_DB !== "1") {
      throw new Error("Explicit disposable test database opt-in is required");
    }
    const url = new URL(rawUrl.replace(/^postgresql\+psycopg:/, "postgresql:"));
    if (
      !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
      !url.pathname.endsWith("_test")
    ) {
      throw new Error("Only a loopback test-suffixed PostgreSQL database is permitted");
    }
    const data = await connect({ databaseUrl: url.toString(), duckdbPath: "" });
    try {
      const client = await data.acquire();
      try {
        const tool = queryHouseholdReportTool({ runner: client });
        const accounts = await client.query<{ id: string }>(
          "SELECT id FROM public.account WHERE provider = $1 AND external_id = $2 " +
            "AND kind = 'checking'",
          ["gls", "household-eur-checking"],
        );
        expect(accounts.rows).toHaveLength(1);
        const accountId = accounts.rows[0]?.id;
        if (!accountId) throw new Error("Synthetic EUR checking fixture is missing");
        for (const granularity of ["day", "month", "year"] as const) {
          const report = await tool.handler({
            date_range: { from: "2026-06-02", to: "2026-06-02" },
            granularity,
            account_ids: [accountId],
          });
          expect(report.current.totals.gross_expenses.eur.amount).toBe("125.4");
          expect(report.current.totals.gross_expenses.eur.complete).toBe(true);
          expect(report.trend).toHaveLength(1);
          expect(report.granularity).toBe(granularity);
        }
      } finally {
        client.release();
      }
    } finally {
      await data.close();
    }
  });
});

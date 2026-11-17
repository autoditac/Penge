import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  getDefaultEnvironment,
  StdioClientTransport,
} from "@modelcontextprotocol/sdk/client/stdio.js";
import { describe, expect, it } from "vitest";
import pg from "pg";

import { connect } from "../src/db.js";
import { getHouseholdMerchantSummaryTool } from "../src/tools/getHouseholdMerchantSummary.js";
import { getHouseholdTransactionDetailTool } from "../src/tools/getHouseholdTransactionDetail.js";
import {
  getSourceCoverageTool,
  type GetSourceCoverageOutput,
} from "../src/tools/getSourceCoverage.js";
import { MCP_READ_ONLY_TOOL_ALLOWLIST } from "../src/sources.js";
import { queryCashflowTool } from "../src/tools/queryCashflow.js";
import { queryNetWorthTool } from "../src/tools/queryNetWorth.js";
import { searchHouseholdTransactionsTool } from "../src/tools/searchHouseholdTransactions.js";
import { searchMerchantReferenceTool } from "../src/tools/searchMerchantReference.js";

const enabled = process.env.PENGE_MCP_REPORT_PG_TEST === "1";
const SYNTHETIC_ENTITY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SYNTHETIC_ACCOUNT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const SYNTHETIC_INSTRUMENT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const SYNTHETIC_HOLDING_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

async function cleanSyntheticFacts(pool: pg.Pool): Promise<void> {
  await pool.query(
    `DELETE FROM public.holding_snapshot
     WHERE id = $1::uuid OR account_id = $2::uuid OR instrument_id = $3::uuid`,
    [SYNTHETIC_HOLDING_ID, SYNTHETIC_ACCOUNT_ID, SYNTHETIC_INSTRUMENT_ID],
  );
  await pool.query("DELETE FROM public.account WHERE id = $1::uuid", [SYNTHETIC_ACCOUNT_ID]);
  await pool.query("DELETE FROM public.instrument WHERE id = $1::uuid", [SYNTHETIC_INSTRUMENT_ID]);
  await pool.query("DELETE FROM public.entity WHERE id = $1::uuid", [SYNTHETIC_ENTITY_ID]);
}

async function isolateCoverageFacts(
  client: pg.PoolClient,
  transactionId: string,
  accountId: string,
): Promise<void> {
  await client.query(
    `CREATE TEMP TABLE account AS
     SELECT *
     FROM public.account
     WHERE id IN ($1::uuid, $2::uuid)`,
    [accountId, SYNTHETIC_ACCOUNT_ID],
  );
  await client.query(
    `CREATE TEMP TABLE transaction AS
     SELECT *
     FROM public.transaction
     WHERE id = $1::uuid`,
    [transactionId],
  );
  await client.query(
    `CREATE TEMP TABLE holding_snapshot AS
     SELECT *
     FROM public.holding_snapshot
     WHERE id = $1::uuid`,
    [SYNTHETIC_HOLDING_ID],
  );
  await client.query(
    `CREATE TEMP TABLE fx_rate AS
     SELECT *
     FROM public.fx_rate
     WHERE base_ccy = 'EUR' AND quote_ccy = 'DKK'
     ORDER BY as_of DESC
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE household_classification AS
     SELECT *
     FROM public.household_classification
     ORDER BY transaction_id
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE household_allocation AS
     SELECT *
     FROM public.household_allocation
     ORDER BY transaction_id, category_id
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE household_audit AS
     SELECT *
     FROM public.household_audit
     ORDER BY created_at DESC
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE household_payment_detail AS
     SELECT *
     FROM public.household_payment_detail
     WHERE provider = 'paypal'
     ORDER BY last_seen_at DESC
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE merchant_reference_generation AS
     SELECT *
     FROM public.merchant_reference_generation
     WHERE status = 'active' AND source_id = 'name-suggestion-index'
     ORDER BY completed_at DESC
     LIMIT 1`,
  );
}

describe.skipIf(!enabled)("source coverage tools on disposable PostgreSQL", () => {
  it("starts the stdio MCP server with only PENGE_DB_URL_FILE", async () => {
    const rawUrl = process.env.PENGE_TEST_DATABASE_URL;
    if (!rawUrl || process.env.PENGE_ALLOW_DESTRUCTIVE_TEST_DB !== "1") {
      throw new Error("Explicit disposable test database opt-in is required");
    }
    const url = rawUrl.replace(/^postgresql\+psycopg:/, "postgresql:");
    const dir = mkdtempSync(join(tmpdir(), "penge-mcp-stdio-"));
    const secretFile = join(dir, "database-url");
    writeFileSync(secretFile, `${url}\n`, { mode: 0o600 });
    const transport = new StdioClientTransport({
      command: join(process.cwd(), "node_modules", ".bin", "tsx"),
      args: ["src/index.ts"],
      cwd: process.cwd(),
      env: {
        ...getDefaultEnvironment(),
        PENGE_DB_URL_FILE: secretFile,
        PENGE_DUCKDB_PATH: join(dir, "marts.duckdb"),
        PENGE_MCP_LOG_DIR: join(dir, "audit"),
      },
      stderr: "pipe",
    });
    const client = new Client(
      { name: "penge-file-only-test", version: "test" },
      { capabilities: {} },
    );
    try {
      await client.connect(transport);
      const tools = await client.listTools();
      expect(tools.tools.map((tool) => tool.name).sort()).toEqual(
        [...MCP_READ_ONLY_TOOL_ALLOWLIST].sort(),
      );
      expect(tools.tools.every((tool) => tool.outputSchema !== undefined)).toBe(true);
      const result = await client.callTool({ name: "_meta", arguments: {} });
      expect(result.structuredContent).toMatchObject({ serverName: "penge-mcp" });
    } finally {
      await client.close();
      rmSync(dir, { recursive: true, force: true });
    }
    // Spawns `tsx src/index.ts`: cold TypeScript transpilation on a shared CI
    // runner exceeds vitest's 5s default before the stdio handshake completes.
  }, 60_000);

  it("fails closed on missing net-worth FX in actual PostgreSQL aggregation", async () => {
    const rawUrl = process.env.PENGE_TEST_DATABASE_URL;
    if (!rawUrl || process.env.PENGE_ALLOW_DESTRUCTIVE_TEST_DB !== "1") {
      throw new Error("Explicit disposable test database opt-in is required");
    }
    const url = rawUrl.replace(/^postgresql\+psycopg:/, "postgresql:");
    const pool = new pg.Pool({ connectionString: url });
    const client = await pool.connect();
    try {
      await client.query(`
        CREATE TEMP TABLE account (
          id uuid PRIMARY KEY,
          provider text NOT NULL,
          kind text NOT NULL
        );
        CREATE TEMP TABLE mart_net_worth_daily (
          account_id uuid NOT NULL,
          as_of date NOT NULL,
          balance_eur numeric,
          balance_dkk numeric
        );
        INSERT INTO account VALUES
          ('11111111-1111-4111-8111-111111111111', 'manual', 'cash'),
          ('22222222-2222-4222-8222-222222222222', 'manual', 'cash');
        INSERT INTO mart_net_worth_daily VALUES
          ('11111111-1111-4111-8111-111111111111', '2026-06-30', 100, 746),
          ('22222222-2222-4222-8222-222222222222', '2026-06-30', NULL, NULL);
      `);
      const tool = queryNetWorthTool({
        runner: {
          query: (sql, params) => client.query(sql, [...params]),
        },
        martTable: "pg_temp.mart_net_worth_daily",
        accountTable: "pg_temp.account",
      });
      await expect(
        tool.handler(
          {
            date_range: { from: "2026-06-30", to: "2026-06-30" },
            currency: "EUR",
            breakdown_by: "none",
            source: "manual_facts",
          },
          { serverName: "postgres-test", serverVersion: "test" },
        ),
      ).rejects.toThrow(/cannot value every selected row in EUR/);
    } finally {
      client.release();
      await pool.end();
    }
  });

  it("returns net-worth and cashflow calendar dates independently of TZ", async () => {
    const rawUrl = process.env.PENGE_TEST_DATABASE_URL;
    if (!rawUrl || process.env.PENGE_ALLOW_DESTRUCTIVE_TEST_DB !== "1") {
      throw new Error("Explicit disposable test database opt-in is required");
    }
    const url = rawUrl.replace(/^postgresql\+psycopg:/, "postgresql:");
    const pool = new pg.Pool({ connectionString: url });
    const client = await pool.connect();
    const previousTimezone = process.env.TZ;
    process.env.TZ = "Europe/Copenhagen";
    try {
      await client.query(`
        CREATE TEMP TABLE account (id uuid PRIMARY KEY, provider text NOT NULL, kind text NOT NULL);
        CREATE TEMP TABLE mart_net_worth_daily (
          account_id uuid NOT NULL, as_of date NOT NULL, balance_eur numeric, balance_dkk numeric
        );
        CREATE TEMP TABLE mart_cashflow_daily (
          as_of date NOT NULL,
          inflow_eur numeric, outflow_eur numeric, net_eur numeric,
          inflow_dkk numeric, outflow_dkk numeric, net_dkk numeric
        );
        INSERT INTO account VALUES ('11111111-1111-4111-8111-111111111111', 'manual', 'cash');
        INSERT INTO mart_net_worth_daily VALUES
          ('11111111-1111-4111-8111-111111111111', '2026-06-02', 100, 746);
        INSERT INTO mart_cashflow_daily VALUES ('2026-06-02', 10, -4, 6, 74.6, -29.84, 44.76);
      `);
      const context = { serverName: "postgres-test", serverVersion: "test" };
      const netWorth = await queryNetWorthTool({
        runner: { query: (sql, params) => client.query(sql, [...params]) },
        martTable: "pg_temp.mart_net_worth_daily",
        accountTable: "pg_temp.account",
      }).handler(
        {
          date_range: { from: "2026-06-02", to: "2026-06-02" },
          currency: "EUR",
          breakdown_by: "none",
        },
        context,
      );
      expect(netWorth.map((row) => row.date)).toEqual(["2026-06-02"]);
      const cashflow = await queryCashflowTool({
        runner: { query: (sql, params) => client.query(sql, [...params]) },
        martTable: "pg_temp.mart_cashflow_daily",
      }).handler(
        { date_range: { from: "2026-06-02", to: "2026-06-02" }, granularity: "day" },
        context,
      );
      expect(cashflow.map((row) => [row.period_start, row.period_end])).toEqual([
        ["2026-06-02", "2026-06-02"],
      ]);
    } finally {
      if (previousTimezone === undefined) delete process.env.TZ;
      else process.env.TZ = previousTimezone;
      client.release(true);
      await pool.end();
    }
  });

  it("executes bounded search and stable-ID detail against synthetic facts", async () => {
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
    const fixturePool = new pg.Pool({ connectionString: url.toString() });
    try {
      await cleanSyntheticFacts(fixturePool);
      await fixturePool.query("INSERT INTO entity (id, name, kind) VALUES ($1::uuid, $2, $3)", [
        SYNTHETIC_ENTITY_ID,
        "Synthetic Manual Owner",
        "person",
      ]);
      await fixturePool.query(
        `INSERT INTO account (id, entity_id, provider, external_id, name, kind, currency)
         VALUES ($1::uuid, $2::uuid, 'manual', $3, $4, 'cash', 'EUR')`,
        [
          SYNTHETIC_ACCOUNT_ID,
          SYNTHETIC_ENTITY_ID,
          "synthetic-manual-account",
          "Synthetic manual account",
        ],
      );
      await fixturePool.query(
        `INSERT INTO instrument (id, name, kind, currency)
         VALUES ($1::uuid, $2, 'cash', 'EUR')`,
        [SYNTHETIC_INSTRUMENT_ID, "Synthetic manual fact"],
      );
      await fixturePool.query(
        `INSERT INTO holding_snapshot (
           id, account_id, instrument_id, as_of, quantity, market_value
         ) VALUES ($1::uuid, $2::uuid, $3::uuid, '2026-06-30', 1, 100)`,
        [SYNTHETIC_HOLDING_ID, SYNTHETIC_ACCOUNT_ID, SYNTHETIC_INSTRUMENT_ID],
      );
      const data = await connect({ databaseUrl: url.toString(), duckdbPath: "" });
      try {
        const client = await data.acquire();
        try {
          const context = { serverName: "postgres-test", serverVersion: "test" };
          const search = searchHouseholdTransactionsTool({ runner: client });
          const page = await search.handler(
            {
              source: "gls",
              date_range: { from: "2026-06-01", to: "2026-06-30" },
              limit: 10,
              offset: 0,
            },
            context,
          );
          search.outputSchema.parse(page);
          expect(page.items.length).toBeGreaterThan(0);
          const transactionId = page.items[0]?.stable_id;
          if (!transactionId) throw new Error("Synthetic GLS transaction fixture is missing");
          const detail = getHouseholdTransactionDetailTool({
            runner: {
              query: (sql, params) => client.query(sql, [...params]),
              async readSnapshot<T>(operation: (runner: typeof client) => Promise<T>): Promise<T> {
                await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
                try {
                  const result = await operation(client);
                  await client.query("COMMIT");
                  return result;
                } catch (error) {
                  await client.query("ROLLBACK");
                  throw error;
                }
              },
            },
          });
          const record = await detail.handler(
            { transaction_id: transactionId, source: "gls" },
            context,
          );
          detail.outputSchema.parse(record);
          expect(record.transaction.stable_id).toBe(transactionId);
          expect(record.ledger_semantics).toBe("single_source_ledger");

          const accountId = page.items[0]?.account_id;
          if (!accountId) throw new Error("Synthetic GLS account fixture is missing");
          const coverageClient = await fixturePool.connect();
          let matrix: GetSourceCoverageOutput;
          try {
            await isolateCoverageFacts(coverageClient, transactionId, accountId);
            await coverageClient.query(
              `UPDATE account SET updated_at = '2000-01-01T00:00:00Z'
               WHERE id = $1::uuid`,
              [accountId],
            );
            await coverageClient.query(
              `UPDATE transaction SET created_at = '2026-12-30T12:00:00Z'
               WHERE id = $1::uuid`,
              [transactionId],
            );
            await coverageClient.query("BEGIN TRANSACTION READ ONLY");
            const coverage = getSourceCoverageTool({
              runner: coverageClient,
              now: () => new Date("2026-12-31T00:00:00Z"),
            });
            try {
              matrix = await coverage.handler(
                {
                  source_ids: [
                    "gls",
                    "manual_facts",
                    "household_classification",
                    "paypal",
                    "ecb_fx",
                    "pfa",
                  ],
                },
                context,
              );
              coverage.outputSchema.parse(matrix);
              await coverageClient.query("COMMIT");
            } catch (error) {
              await coverageClient.query("ROLLBACK");
              throw error;
            }
          } finally {
            coverageClient.release();
          }
          expect(matrix.sources).toHaveLength(6);
          expect(matrix.sources.find((source) => source.id === "gls")?.coverage.account_count).toBe(
            1,
          );
          expect(
            matrix.sources.find((source) => source.id === "gls")?.coverage.transaction_count,
          ).toBe(1);
          expect(matrix.sources.find((source) => source.id === "gls")?.coverage.freshness).toBe(
            "fresh",
          );
          const manual = matrix.sources.find((source) => source.id === "manual_facts")?.coverage;
          expect(manual?.account_count).toBe(1);
          expect(manual?.holding_count).toBe(1);
          expect(manual?.completeness).toBe("complete");
          expect(
            matrix.sources.find((source) => source.id === "household_classification")?.coverage
              .transaction_count,
          ).toBeGreaterThan(0);
          expect(
            matrix.sources.find((source) => source.id === "household_classification")?.coverage
              .evidence_count,
          ).toBeGreaterThan(0);
          expect(
            matrix.sources.find((source) => source.id === "paypal")?.coverage.evidence_count,
          ).toBeGreaterThan(0);
          expect(
            matrix.sources.find((source) => source.id === "ecb_fx")?.coverage.evidence_count,
          ).toBeGreaterThan(0);
          expect(matrix.sources.find((source) => source.id === "pfa")?.coverage.completeness).toBe(
            "missing",
          );
        } finally {
          client.release();
        }
      } finally {
        await data.close();
      }
    } finally {
      await cleanSyntheticFacts(fixturePool);
      await fixturePool.end();
    }
  });

  it("serializes calendar dates and derives stale review state independently of TZ", async () => {
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
    const accountId = "e1e1e1e1-e1e1-4e1e-8e1e-e1e1e1e1e1e1";
    const current = "e2e2e2e2-e2e2-4e2e-8e2e-e2e2e2e2e2e2";
    const sourceDrift = "e3e3e3e3-e3e3-4e3e-8e3e-e3e3e3e3e3e3";
    const detailDrift = "e4e4e4e4-e4e4-4e4e-8e4e-e4e4e4e4e4e4";
    const currentDetail = "e5e5e5e5-e5e5-4e5e-8e5e-e5e5e5e5e5e5";
    const revisedDetail = "e6e6e6e6-e6e6-4e6e-8e6e-e6e6e6e6e6e6";
    const pool = new pg.Pool({ connectionString: url.toString() });
    const client = await pool.connect();
    const previousTimezone = process.env.TZ;
    process.env.TZ = "Europe/Copenhagen";
    let destroy = false;
    try {
      // Session-local shadows keep the shared seeded tables untouched.
      for (const table of [
        "account",
        "transaction",
        "household_classification",
        "household_merchant",
        "household_allocation",
        "household_audit",
        "household_payment_detail",
        "household_payment_detail_link",
      ]) {
        destroy = true;
        await client.query(`CREATE TEMP TABLE ${table} (LIKE public.${table} INCLUDING DEFAULTS)`);
      }
      await client.query(
        `INSERT INTO account (id, entity_id, provider, name, kind, currency)
         VALUES ($1::uuid, $1::uuid, 'gls', 'Synthetic TZ account', 'checking', 'EUR')`,
        [accountId],
      );
      // 22:30Z on June 1 is already June 2 in Copenhagen; the contract is the UTC date.
      await client.query(
        `INSERT INTO transaction (id, account_id, ts, value_date, kind, amount, counterparty)
         VALUES
           ($1::uuid, $4::uuid, '2026-06-01T22:30:00Z', '2026-06-02', 'payment', -12.50, 'Shop'),
           ($2::uuid, $4::uuid, '2026-06-01T22:30:00Z', '2026-06-02', 'payment', -20.00, 'Shop'),
           ($3::uuid, $4::uuid, '2026-06-01T22:30:00Z', '2026-06-02', 'payment', -30.00, 'Shop')`,
        [current, sourceDrift, detailDrift, accountId],
      );
      await client.query(
        `INSERT INTO household_classification (
           transaction_id, treatment, review_state, identity_confirmed, provenance, revision,
           source_amount, source_currency, source_ts, source_counterparty, source_kind,
           explanation
         )
         SELECT t.id, 'expense', 'classified', false, 'manual', 1,
           CASE WHEN t.id = $1::uuid THEN -21.00 ELSE t.amount END,
           'EUR', t.ts, t.counterparty, t.kind, 'synthetic approval'
         FROM transaction AS t`,
        [sourceDrift],
      );
      await client.query(
        `INSERT INTO household_payment_detail (
           id, provider, source_account_id, external_id, ts, amount, currency,
           event_kind, source_fields, revision
         ) VALUES
           ($1::uuid, 'paypal', 'synthetic', 'detail-current', '2026-06-01T22:00:00Z',
            12.50, 'EUR', 'purchase', '{}'::jsonb, 1),
           ($2::uuid, 'paypal', 'synthetic', 'detail-revised', '2026-06-01T22:00:00Z',
            30.00, 'EUR', 'purchase', '{}'::jsonb, 2)`,
        [currentDetail, revisedDetail],
      );
      await client.query(
        `INSERT INTO household_payment_detail_link (
           transaction_id, detail_id, bank_amount, detail_revision
         ) VALUES ($1::uuid, $2::uuid, -12.50, 1), ($3::uuid, $4::uuid, -30.00, 1)`,
        [current, currentDetail, detailDrift, revisedDetail],
      );

      const context = { serverName: "postgres-test", serverVersion: "test" };
      const search = searchHouseholdTransactionsTool({ runner: client });
      const page = await search.handler(
        {
          source: "gls",
          account_ids: [accountId],
          date_range: { from: "2026-06-01", to: "2026-06-01" },
          limit: 10,
          offset: 0,
        },
        context,
      );
      search.outputSchema.parse(page);
      const states = Object.fromEntries(
        page.items.map((item) => [item.stable_id, item.classification?.review_state]),
      );
      expect(states).toEqual({
        [current]: "classified",
        [sourceDrift]: "needs_review",
        [detailDrift]: "needs_review",
      });
      expect(page.items.map((item) => item.transaction_date)).toEqual([
        "2026-06-01",
        "2026-06-01",
        "2026-06-01",
      ]);

      const detail = getHouseholdTransactionDetailTool({
        runner: {
          query: (sql, params) => client.query(sql, [...params]),
          readSnapshot: (operation) => operation(client),
        },
      });
      for (const [transactionId, expected] of [
        [current, "classified"],
        [sourceDrift, "needs_review"],
        [detailDrift, "needs_review"],
      ] as const) {
        const record = await detail.handler(
          { transaction_id: transactionId, source: "gls" },
          context,
        );
        detail.outputSchema.parse(record);
        expect(record.transaction.value_date).toBe("2026-06-02");
        expect(record.classification?.review_state).toBe(expected);
      }
    } finally {
      if (previousTimezone === undefined) delete process.env.TZ;
      else process.env.TZ = previousTimezone;
      // Destroying the session drops every temp shadow table.
      client.release(destroy);
      await pool.end();
    }
  });

  it("matches Unicode text consistently and derives Enable Banking coverage conservatively", async () => {
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
    const gls = "f1f1f1f1-f1f1-4f1f-8f1f-f1f1f1f1f1f1";
    const ebank = "f2f2f2f2-f2f2-4f2f-8f2f-f2f2f2f2f2f2";
    const lunar = "f3f3f3f3-f3f3-4f3f-8f3f-f3f3f3f3f3f3";
    const aeTxn = "f4f4f4f4-f4f4-4f4f-8f4f-f4f4f4f4f4f4";
    const dottedTxn = "f5f5f5f5-f5f5-4f5f-8f5f-f5f5f5f5f5f5";
    const merchant = "f6f6f6f6-f6f6-4f6f-8f6f-f6f6f6f6f6f6";
    const generation = "f7f7f7f7-f7f7-4f7f-8f7f-f7f7f7f7f7f7";
    const labelOnly = "f8f8f8f8-f8f8-4f8f-8f8f-f8f8f8f8f8f8";
    const aliased = "f9f9f9f9-f9f9-4f9f-8f9f-f9f9f9f9f9f9";
    const pool = new pg.Pool({ connectionString: url.toString() });
    const client = await pool.connect();
    let destroy = false;
    try {
      // Session-local shadows keep the shared seeded tables untouched.
      for (const table of [
        "account",
        "transaction",
        "household_classification",
        "household_merchant",
        "merchant_reference_generation",
        "merchant_reference",
        "merchant_reference_alias",
      ]) {
        destroy = true;
        await client.query(`CREATE TEMP TABLE ${table} (LIKE public.${table} INCLUDING DEFAULTS)`);
      }
      await client.query(
        `INSERT INTO account (id, entity_id, provider, name, kind, currency) VALUES
           ($1::uuid, $1::uuid, 'gls', 'Synthetic GLS', 'checking', 'EUR'),
           ($2::uuid, $2::uuid, 'ebank', 'Synthetic EBank', 'checking', 'EUR'),
           ($3::uuid, $3::uuid, 'lunar', 'Synthetic Lunar', 'checking', 'DKK')`,
        [gls, ebank, lunar],
      );
      await client.query(
        `INSERT INTO transaction (id, account_id, ts, value_date, kind, amount, counterparty)
         VALUES
           ($1::uuid, $3::uuid, '2026-06-01T10:00:00Z', '2026-06-01', 'payment', -4.00,
            '\u00c6ble Bager'),
           ($2::uuid, $4::uuid, '2026-06-01T11:00:00Z', '2026-06-01', 'payment', -5.00,
            'Synthetic Shop')`,
        [aeTxn, dottedTxn, gls, ebank],
      );
      await client.query(
        `INSERT INTO household_merchant (id, name, identity_kind, revision)
         VALUES ($1::uuid, '\u0130stanbul Kiosk', 'stable', 1)`,
        [merchant],
      );
      await client.query(
        `INSERT INTO household_classification (
           transaction_id, treatment, review_state, merchant_id, identity_confirmed, provenance,
           revision, source_amount, source_currency, source_ts, source_counterparty,
           source_kind, explanation
         ) VALUES ($1::uuid, 'expense', 'classified', $2::uuid, false, 'manual', 1, -5.00,
           'EUR', '2026-06-01T11:00:00Z', 'Synthetic Shop', 'payment', 'synthetic')`,
        [dottedTxn, merchant],
      );
      await client.query(
        `INSERT INTO merchant_reference_generation (
           id, source_id, source_version, package_integrity, catalog_sha256,
           source_generated_at, retrieved_at, source_url, license, record_count, status,
           completed_at
         ) VALUES ($1::uuid, 'name-suggestion-index', 'fixture-v1', 'sha512-synthetic',
           repeat('a', 64), '2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z',
           'https://example.invalid/nsi', 'BSD-3-Clause', 2, 'active', '2026-06-01T00:00:00Z')`,
        [generation],
      );
      await client.query(
        `INSERT INTO merchant_reference (
           id, generation_id, source_id, source_entity_id, label, category_path,
           source_version, source_revision_at, source_url, license
         ) VALUES
           ($1::uuid, $3::uuid, 'name-suggestion-index', 'synthetic-label-only',
            'Stra\u00dfe Nord', 'shop/Stra\u00dfe', 'fixture-v1', '2026-06-01T00:00:00Z',
            'https://example.invalid/nsi', 'BSD-3-Clause'),
           ($2::uuid, $3::uuid, 'name-suggestion-index', 'synthetic-aliased',
            'Synthetic Market', 'shop/market', 'fixture-v1', '2026-06-01T00:00:00Z',
            'https://example.invalid/nsi', 'BSD-3-Clause')`,
        [labelOnly, aliased, generation],
      );
      // normalized_alias is written by Python normalize_alias(): NFKC + casefold.
      await client.query(
        `INSERT INTO merchant_reference_alias (
           id, generation_id, reference_id, alias, normalized_alias
         ) VALUES (gen_random_uuid(), $1::uuid, $2::uuid, 'Gro\u00dfmarkt', 'grossmarkt')`,
        [generation, aliased],
      );

      const context = { serverName: "postgres-test", serverVersion: "test" };
      const search = searchHouseholdTransactionsTool({ runner: client });
      for (const [query, expected] of [
        ["\u00c6BLE", aeTxn],
        ["\u0130STANBUL", dottedTxn],
      ] as const) {
        const page = await search.handler(
          search.inputSchema.parse({ query, date_range: { from: "2026-06-01", to: "2026-06-01" } }),
          context,
        );
        search.outputSchema.parse(page);
        expect(page.items.map((item) => item.stable_id)).toEqual([expected]);
        expect(page.total).toBe(1);
      }

      const merchants = getHouseholdMerchantSummaryTool({ runner: client });
      const merchantPage = await merchants.handler(
        merchants.inputSchema.parse({ query: "\u0130STANBUL" }),
        context,
      );
      merchants.outputSchema.parse(merchantPage);
      expect(merchantPage.total).toBe(1);
      expect(merchantPage.merchants.map((entry) => entry.merchant_id)).toEqual([merchant]);

      const references = searchMerchantReferenceTool({ runner: client });
      for (const [args, expected] of [
        [{ query: "STRA\u00dfE" }, [labelOnly]],
        [{ query: "nord", category_prefix: "SHOP/STRA\u00dfE" }, [labelOnly]],
        [{ query: "GROSSMARKT" }, [aliased]],
        [{ query: "Gro\u00dfmarkt" }, [aliased]],
      ] as const) {
        const page = await references.handler(references.inputSchema.parse(args), context);
        references.outputSchema.parse(page);
        expect(page.results.map((entry) => entry.reference_id)).toEqual(expected);
        expect(page.total).toBe(expected.length);
      }

      const coverage = getSourceCoverageTool({ runner: client });
      const partial = await coverage.handler(
        coverage.inputSchema.parse({ source_ids: ["enable_banking"] }),
        context,
      );
      coverage.outputSchema.parse(partial);
      expect(partial.complete).toBe(false);
      expect(partial.sources[0]?.coverage).toMatchObject({
        completeness: "partial",
        freshness: "unknown",
        latest_observed_at: null,
        account_count: 3,
        transaction_count: 2,
      });

      await client.query(
        `INSERT INTO transaction (id, account_id, ts, value_date, kind, amount, counterparty)
         VALUES (gen_random_uuid(), $1::uuid, '2026-06-01T12:00:00Z', '2026-06-01', 'payment',
           -6.00, 'Synthetic Cafe')`,
        [lunar],
      );
      const complete = await coverage.handler({ source_ids: ["enable_banking"] }, context);
      expect(complete.sources[0]?.coverage).toMatchObject({
        completeness: "complete",
        freshness: "fresh",
        transaction_count: 3,
      });
    } finally {
      // Destroying the session drops every temp shadow table.
      client.release(destroy);
      await pool.end();
    }
  });
});

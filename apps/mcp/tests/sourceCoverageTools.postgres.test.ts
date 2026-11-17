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
import { getHouseholdTaxonomySummaryTool } from "../src/tools/getHouseholdTaxonomySummary.js";
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
    `CREATE TEMP TABLE mart_net_worth_daily
     (LIKE analytics_marts.mart_net_worth_daily INCLUDING DEFAULTS)`,
  );
  await client.query(
    "CREATE TEMP TABLE import_session (LIKE public.import_session INCLUDING DEFAULTS)",
  );
  await client.query("CREATE TEMP TABLE import_row (LIKE public.import_row INCLUDING DEFAULTS)");
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
    `CREATE TEMP TABLE household_payment_detail_link AS
     SELECT link.*
     FROM public.household_payment_detail_link AS link
     INNER JOIN household_payment_detail AS detail ON detail.id = link.detail_id
     WHERE link.transaction_id = $1::uuid`,
    [transactionId],
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

  it("excludes unsupported currencies from transaction pages and totals", async () => {
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
    const euroAccount = "10101010-1010-4010-8010-101010101010";
    const dkkAccount = "20202020-2020-4020-8020-202020202020";
    const usdAccount = "30303030-3030-4030-8030-303030303030";
    const euroTransaction = "40404040-4040-4040-8040-404040404040";
    const dkkTransaction = "50505050-5050-4050-8050-505050505050";
    const usdTransaction = "60606060-6060-4060-8060-606060606060";
    const pool = new pg.Pool({ connectionString: url.toString() });
    const client = await pool.connect();
    let destroy = false;
    try {
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
         VALUES
           ($1::uuid, $1::uuid, 'gls', 'Synthetic EUR account', 'checking', 'EUR'),
           ($2::uuid, $2::uuid, 'lunar', 'Synthetic DKK account', 'checking', 'DKK'),
           ($3::uuid, $3::uuid, 'gls', 'Synthetic USD account', 'checking', 'USD')`,
        [euroAccount, dkkAccount, usdAccount],
      );
      await client.query(
        `INSERT INTO transaction (id, account_id, ts, value_date, kind, amount, counterparty)
         VALUES
           ($1::uuid, $4::uuid, '2026-06-01T10:00:00Z', '2026-06-01', 'payment', -1, 'Euro'),
           ($2::uuid, $5::uuid, '2026-06-01T11:00:00Z', '2026-06-01', 'payment', -2, 'Krone'),
           ($3::uuid, $6::uuid, '2026-06-01T12:00:00Z', '2026-06-01', 'payment', -3, 'Dollar')`,
        [euroTransaction, dkkTransaction, usdTransaction, euroAccount, dkkAccount, usdAccount],
      );

      const search = searchHouseholdTransactionsTool({ runner: client });
      const context = { serverName: "postgres-test", serverVersion: "test" };
      const base = { date_range: { from: "2026-06-01", to: "2026-06-01" }, limit: 1 };
      const first = await search.handler(search.inputSchema.parse(base), context);
      const second = await search.handler(
        search.inputSchema.parse({ ...base, offset: 1 }),
        context,
      );
      const afterLast = await search.handler(
        search.inputSchema.parse({ ...base, offset: 2 }),
        context,
      );
      const usdOnly = await search.handler(
        search.inputSchema.parse({ ...base, account_ids: [usdAccount] }),
        context,
      );
      for (const page of [first, second, afterLast, usdOnly]) search.outputSchema.parse(page);
      expect(first.total).toBe(2);
      expect(first.items.map((row) => [row.stable_id, row.currency])).toEqual([
        [dkkTransaction, "DKK"],
      ]);
      expect(second.total).toBe(2);
      expect(second.items.map((row) => [row.stable_id, row.currency])).toEqual([
        [euroTransaction, "EUR"],
      ]);
      expect(afterLast).toMatchObject({ total: 2, items: [] });
      expect(usdOnly).toMatchObject({ total: 0, items: [] });
    } finally {
      client.release(destroy);
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
            await coverageClient.query(
              `INSERT INTO holding_snapshot
                 (id, account_id, instrument_id, as_of, quantity, market_value, created_at)
               VALUES (gen_random_uuid(), $1::uuid, $2::uuid, '2026-12-30', 1, 100,
                 '2026-12-30T12:00:00Z')`,
              [accountId, SYNTHETIC_INSTRUMENT_ID],
            );
            await coverageClient.query(
              `INSERT INTO mart_net_worth_daily
                 (entity_id, account_id, account_currency, as_of, balance_acct_ccy,
                  balance_eur, balance_dkk)
               SELECT entity_id, id, currency, '2026-12-30', 100, 100, 745
               FROM account WHERE id = $1::uuid`,
              [accountId],
            );
            await coverageClient.query(
              `INSERT INTO mart_net_worth_daily
                 (entity_id, account_id, account_currency, as_of, balance_acct_ccy,
                  balance_eur, balance_dkk)
               SELECT a.entity_id, a.id, a.currency, h.as_of, h.market_value,
                 h.market_value, h.market_value * 7.45
               FROM holding_snapshot AS h INNER JOIN account AS a ON a.id = h.account_id
               WHERE h.id = $1::uuid`,
              [SYNTHETIC_HOLDING_ID],
            );
            await coverageClient.query("BEGIN TRANSACTION READ ONLY");
            const coverage = getSourceCoverageTool({
              runner: coverageClient,
              martTable: "pg_temp.mart_net_worth_daily",
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
            coverageClient.release(true);
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
    const category = "fafafafa-fafa-4afa-8afa-fafafafafafa";
    const unsupportedAccount = "fbfbfbfb-fbfb-4bfb-8bfb-fbfbfbfbfbfb";
    const nordnet = "fcfcfcfc-fcfc-4cfc-8cfc-fcfcfcfcfcfc";
    const transactionImport = "fdfdfdfd-fdfd-4dfd-8dfd-fdfdfdfdfdfd";
    const holdingImport = "fefefefe-fefe-4efe-8efe-fefefefefefe";
    const pool = new pg.Pool({ connectionString: url.toString() });
    const client = await pool.connect();
    let destroy = false;
    try {
      // Session-local shadows keep the shared seeded tables untouched.
      for (const table of [
        "account",
        "transaction",
        "holding_snapshot",
        "fx_rate",
        "household_classification",
        "household_category",
        "household_merchant",
        "household_merchant_alias",
        "household_rule",
        "household_allocation",
        "household_audit",
        "household_payment_detail",
        "household_payment_detail_link",
        "import_session",
        "import_row",
        "merchant_reference_generation",
        "merchant_reference",
        "merchant_reference_alias",
      ]) {
        destroy = true;
        await client.query(`CREATE TEMP TABLE ${table} (LIKE public.${table} INCLUDING DEFAULTS)`);
      }
      await client.query(
        `CREATE TEMP TABLE mart_net_worth_daily
         (LIKE analytics_marts.mart_net_worth_daily INCLUDING DEFAULTS)`,
      );
      await client.query(
        `INSERT INTO account (id, entity_id, provider, name, kind, currency) VALUES
           ($1::uuid, $1::uuid, 'gls', 'Synthetic GLS', 'checking', 'EUR'),
           ($2::uuid, $2::uuid, 'ebank', 'Synthetic EBank', 'checking', 'EUR'),
           ($3::uuid, $3::uuid, 'lunar', 'Synthetic Lunar', 'checking', 'DKK')`,
        [gls, ebank, lunar],
      );
      await client.query(
        `INSERT INTO transaction
           (id, account_id, ts, value_date, kind, amount, counterparty, created_at)
         VALUES
           ($1::uuid, $3::uuid, '2026-06-01T10:00:00Z', '2026-06-01', 'payment', -4.00,
            '\u00c6ble Bager', '2026-10-03T00:00:00Z'),
           ($2::uuid, $4::uuid, '2026-06-01T11:00:00Z', '2026-06-01', 'payment', -5.00,
            'Synthetic Shop', '2026-10-03T00:00:00Z')`,
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
         ) VALUES
           (gen_random_uuid(), $1::uuid, $2::uuid, 'Gro\u00dfmarkt', 'grossmarkt'),
           (gen_random_uuid(), $1::uuid, $3::uuid, 'Zeichen\ufeffKiosk', 'zeichen\ufeffkiosk')`,
        [generation, aliased, labelOnly],
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

      const unicodeName = `${"\u{1F9FE}".repeat(94)} DE89370400440532013000`;
      await client.query(
        `INSERT INTO household_category (id, name, kind) VALUES ($1::uuid, $2, 'expense')`,
        [category, unicodeName],
      );
      const taxonomy = getHouseholdTaxonomySummaryTool({ runner: client });
      const categoryPage = await taxonomy.handler(taxonomy.inputSchema.parse({}), context);
      taxonomy.outputSchema.parse(categoryPage);
      expect(categoryPage.entries[0]?.name).toBe(`${"\u{1F9FE}".repeat(94)} [REDACTED]`);

      const references = searchMerchantReferenceTool({ runner: client });
      for (const [args, expected] of [
        [{ query: "STRA\u00dfE" }, [labelOnly]],
        [{ query: "nord", category_prefix: "SHOP/STRA\u00dfE" }, [labelOnly]],
        [{ query: "GROSSMARKT" }, [aliased]],
        [{ query: "Gro\u00dfmarkt" }, [aliased]],
        // Python str.split() whitespace: U+001C..U+001F/U+0085 collapse, U+FEFF does not.
        [{ query: "\u001cGRO\u00dfMARKT\u0085" }, [aliased]],
        [{ query: "ZEICHEN\ufeffKIOSK" }, [labelOnly]],
      ] as const) {
        const page = await references.handler(references.inputSchema.parse(args), context);
        references.outputSchema.parse(page);
        expect(page.results.map((entry) => entry.reference_id)).toEqual(expected);
        expect(page.total).toBe(expected.length);
      }

      const coverage = getSourceCoverageTool({
        runner: client,
        martTable: "pg_temp.mart_net_worth_daily",
        now: () => new Date("2026-10-04T08:00:00.000Z"),
      });
      const bankWithoutBalance = await coverage.handler({ source_ids: ["gls"] }, context);
      expect(bankWithoutBalance.sources[0]?.coverage).toMatchObject({
        completeness: "partial",
        freshness: "unknown",
        transaction_count: 1,
        holding_count: 0,
      });
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
        holding_count: 0,
      });

      await client.query(
        `INSERT INTO transaction
           (id, account_id, ts, value_date, kind, amount, counterparty, created_at)
         VALUES (gen_random_uuid(), $1::uuid, '2026-06-01T12:00:00Z', '2026-06-01', 'payment',
           -6.00, 'Synthetic Cafe', '2026-10-03T00:00:00Z')`,
        [lunar],
      );
      await client.query(
        `INSERT INTO holding_snapshot
           (id, account_id, instrument_id, as_of, quantity, market_value, created_at)
         VALUES
           (gen_random_uuid(), $1::uuid, $4::uuid, '2026-10-02', 1, 10, '2026-10-02T00:00:00Z'),
           (gen_random_uuid(), $2::uuid, $4::uuid, '2026-10-03', 1, 20, '2026-10-03T00:00:00Z'),
           (gen_random_uuid(), $3::uuid, $4::uuid, '2026-10-01', 1, 30, '2026-10-01T00:00:00Z')`,
        [gls, ebank, lunar, SYNTHETIC_INSTRUMENT_ID],
      );
      const missingMart = await coverage.handler({ source_ids: ["enable_banking"] }, context);
      expect(missingMart.sources[0]?.coverage).toMatchObject({
        completeness: "partial",
        freshness: "unknown",
        holding_count: 3,
      });
      await client.query(
        `INSERT INTO mart_net_worth_daily
           (entity_id, account_id, account_currency, as_of, balance_acct_ccy,
            balance_eur, balance_dkk)
         VALUES
           ($1::uuid, $1::uuid, 'EUR', '2026-10-02', 10, 10, 74.5),
           ($2::uuid, $2::uuid, 'EUR', '2026-10-03', 20, 20, 149),
           ($3::uuid, $3::uuid, 'DKK', '2026-10-01', 30, 4, 30)`,
        [gls, ebank, lunar],
      );
      const complete = await coverage.handler({ source_ids: ["enable_banking"] }, context);
      expect(complete.sources[0]?.coverage).toMatchObject({
        completeness: "complete",
        freshness: "fresh",
        transaction_count: 3,
        holding_count: 3,
        evidence_count: 6,
        latest_observed_at: "2026-10-01T00:00:00.000Z",
      });
      await client.query("UPDATE holding_snapshot SET market_value = 11 WHERE account_id = $1", [
        gls,
      ]);
      expect(
        (await coverage.handler({ source_ids: ["gls"] }, context)).sources[0]?.coverage,
      ).toMatchObject({ completeness: "partial", freshness: "unknown" });

      await client.query(
        `INSERT INTO account (id, entity_id, provider, external_id, name, kind, currency)
         VALUES ($1::uuid, $1::uuid, 'nordnet', 'synthetic-broker-account',
           'Synthetic Nordnet', 'brokerage', 'EUR')`,
        [nordnet],
      );
      await client.query(
        `INSERT INTO transaction
           (id, account_id, ts, value_date, kind, amount, counterparty, created_at)
         VALUES (gen_random_uuid(), $1::uuid, '2026-08-01T10:00:00Z', '2026-08-01',
           'payment', -1, 'Synthetic Shop', '2026-08-01T00:00:00Z')`,
        [nordnet],
      );
      await client.query(
        `INSERT INTO holding_snapshot
           (id, account_id, instrument_id, as_of, quantity, market_value, created_at)
         VALUES (gen_random_uuid(), $1::uuid, $2::uuid, '2026-08-01', 1, 100,
           '2026-08-01T00:00:00Z')`,
        [nordnet, SYNTHETIC_INSTRUMENT_ID],
      );
      await client.query(
        `INSERT INTO mart_net_worth_daily
           (entity_id, account_id, account_currency, as_of, balance_acct_ccy,
            balance_eur, balance_dkk)
         VALUES ($1::uuid, $1::uuid, 'EUR', '2026-08-01', 100, 100, 745)`,
        [nordnet],
      );
      const readNordnet = async () =>
        (await coverage.handler({ source_ids: ["nordnet"] }, context)).sources[0]?.coverage;
      expect(await readNordnet()).toMatchObject({ completeness: "complete", freshness: "stale" });
      await client.query(
        `INSERT INTO import_session
           (id, source, original_filename, content_sha256, stored_path, status, params,
            expires_at, committed_at)
         VALUES
           ($1::uuid, 'nordnet_transactions', 'synthetic.csv', repeat('a', 64), 'synthetic',
            'committed', '{}'::jsonb, '2026-12-01T00:00:00Z', '2026-10-03T00:00:00Z'),
           ($2::uuid, 'nordnet_holdings', 'synthetic.csv', repeat('b', 64), 'synthetic',
            'staged', jsonb_build_object('account_number', 'synthetic-broker-account'),
            '2026-12-01T00:00:00Z', NULL)`,
        [transactionImport, holdingImport],
      );
      await client.query(
        `INSERT INTO import_row (id, session_id, row_index, kind, payload, excluded)
         VALUES
           (gen_random_uuid(), $1::uuid, 0, 'transaction',
            jsonb_build_object('account_number', 'synthetic-broker-account'), true),
           (gen_random_uuid(), $2::uuid, 0, 'holding', '{}'::jsonb, false)`,
        [transactionImport, holdingImport],
      );
      expect(await readNordnet()).toMatchObject({ freshness: "stale" });
      await client.query("UPDATE import_row SET excluded = false WHERE session_id = $1", [
        transactionImport,
      ]);
      expect(await readNordnet()).toMatchObject({ freshness: "stale" });
      await client.query(
        `UPDATE import_session SET status = 'committed', committed_at = '2026-10-02T00:00:00Z'
         WHERE id = $1`,
        [holdingImport],
      );
      expect(await readNordnet()).toMatchObject({
        freshness: "fresh",
        latest_observed_at: "2026-10-02T00:00:00.000Z",
      });
      await client.query("DELETE FROM pg_temp.import_row WHERE session_id = $1", [holdingImport]);
      expect(await readNordnet()).toMatchObject({ freshness: "stale" });
      await client.query(
        `UPDATE import_session
         SET params = params || '{"empty_snapshot_confirmed": true}'::jsonb WHERE id = $1`,
        [holdingImport],
      );
      await client.query(
        `UPDATE holding_snapshot SET as_of = '2026-10-02', market_value = 0
         WHERE account_id = $1`,
        [nordnet],
      );
      await client.query(
        `UPDATE mart_net_worth_daily
         SET as_of = '2026-10-02', balance_acct_ccy = 0, balance_eur = 0, balance_dkk = 0
         WHERE account_id = $1`,
        [nordnet],
      );
      expect(await readNordnet()).toMatchObject({
        freshness: "fresh",
        latest_observed_at: "2026-10-02T00:00:00.000Z",
      });
      await client.query(
        `UPDATE mart_net_worth_daily
         SET balance_acct_ccy = 11, balance_eur = 11, balance_dkk = 81.95
         WHERE account_id = $1`,
        [gls],
      );
      expect(
        (await coverage.handler({ source_ids: ["gls"] }, context)).sources[0]?.coverage,
      ).toMatchObject({ completeness: "complete", freshness: "fresh" });
      await client.query(
        "UPDATE mart_net_worth_daily SET balance_dkk = NULL WHERE account_id = $1",
        [gls],
      );
      expect(
        (await coverage.handler({ source_ids: ["gls"] }, context)).sources[0]?.coverage,
      ).toMatchObject({ completeness: "partial", freshness: "unknown" });
      await client.query(
        "UPDATE mart_net_worth_daily SET balance_dkk = 81.95 WHERE account_id = $1",
        [gls],
      );
      // An unvalued latest position is mart-valued as 0; a matching 0 balance must not
      // make the account complete or fresh.
      await client.query("UPDATE holding_snapshot SET market_value = NULL WHERE account_id = $1", [
        gls,
      ]);
      await client.query(
        `UPDATE mart_net_worth_daily SET balance_acct_ccy = 0, balance_eur = 0, balance_dkk = 0
         WHERE account_id = $1`,
        [gls],
      );
      expect(
        (await coverage.handler({ source_ids: ["gls"] }, context)).sources[0]?.coverage,
      ).toMatchObject({ completeness: "partial", freshness: "unknown", holding_count: 1 });
      await client.query("UPDATE holding_snapshot SET market_value = 11 WHERE account_id = $1", [
        gls,
      ]);
      await client.query(
        `UPDATE mart_net_worth_daily SET balance_acct_ccy = 11, balance_eur = 11,
           balance_dkk = 81.95
         WHERE account_id = $1`,
        [gls],
      );
      expect(
        (await coverage.handler({ source_ids: ["gls"] }, context)).sources[0]?.coverage,
      ).toMatchObject({ completeness: "complete", freshness: "fresh" });
      await client.query(
        `INSERT INTO account (id, entity_id, provider, name, kind, currency)
         VALUES ($1::uuid, $1::uuid, 'gls', 'Synthetic second account', 'checking', 'EUR')`,
        [unsupportedAccount],
      );
      await client.query(
        `INSERT INTO transaction
           (id, account_id, ts, value_date, kind, amount, counterparty, created_at)
         VALUES (gen_random_uuid(), $1::uuid, '2026-06-01T10:00:00Z', '2026-06-01',
           'payment', -1, 'Synthetic Shop', '2026-10-03T00:00:00Z')`,
        [unsupportedAccount],
      );
      expect(
        (await coverage.handler({ source_ids: ["gls"] }, context)).sources[0]?.coverage,
      ).toMatchObject({
        completeness: "partial",
        freshness: "unknown",
        transaction_count: 2,
        holding_count: 1,
      });
      await client.query(
        `INSERT INTO holding_snapshot
           (id, account_id, instrument_id, as_of, quantity, market_value, created_at)
         VALUES (gen_random_uuid(), $1::uuid, $2::uuid, '2026-10-03', 1, 1,
           '2026-10-03T00:00:00Z')`,
        [unsupportedAccount, SYNTHETIC_INSTRUMENT_ID],
      );
      await client.query(
        `INSERT INTO mart_net_worth_daily
           (entity_id, account_id, account_currency, as_of, balance_acct_ccy,
            balance_eur, balance_dkk)
         VALUES ($1::uuid, $1::uuid, 'EUR', '2026-10-03', 1, 1, 7.45)`,
        [unsupportedAccount],
      );
      expect(
        (await coverage.handler({ source_ids: ["gls"] }, context)).sources[0]?.coverage,
      ).toMatchObject({ completeness: "complete", freshness: "fresh", holding_count: 2 });
      await client.query("UPDATE account SET currency = 'USD' WHERE id = $1", [unsupportedAccount]);
      await client.query(
        "UPDATE mart_net_worth_daily SET account_currency = 'USD' WHERE account_id = $1",
        [unsupportedAccount],
      );
      expect(
        (await coverage.handler({ source_ids: ["gls"] }, context)).sources[0]?.coverage,
      ).toMatchObject({ completeness: "partial", freshness: "unknown" });
    } finally {
      // Destroying the session drops every temp shadow table.
      client.release(destroy);
      await pool.end();
    }
  });

  it("reports PayPal coverage only for details accessible through bounded transaction links", async () => {
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
    const account = "a1a1a1a1-a1a1-4a1a-8a1a-a1a1a1a1a1a1";
    const manual = "a2a2a2a2-a2a2-4a2a-8a2a-a2a2a2a2a2a2";
    const foreign = "a3a3a3a3-a3a3-4a3a-8a3a-a3a3a3a3a3a3";
    const bankTx = "a4a4a4a4-a4a4-4a4a-8a4a-a4a4a4a4a4a4";
    const manualTx = "a5a5a5a5-a5a5-4a5a-8a5a-a5a5a5a5a5a5";
    const foreignTx = "a6a6a6a6-a6a6-4a6a-8a6a-a6a6a6a6a6a6";
    const firstDetail = "a7a7a7a7-a7a7-4a7a-8a7a-a7a7a7a7a7a7";
    const secondDetail = "a8a8a8a8-a8a8-4a8a-8a8a-a8a8a8a8a8a8";
    const pool = new pg.Pool({ connectionString: url.toString() });
    const client = await pool.connect();
    let destroy = false;
    try {
      for (const table of [
        "account",
        "transaction",
        "holding_snapshot",
        "fx_rate",
        "household_classification",
        "household_category",
        "household_merchant",
        "household_allocation",
        "household_audit",
        "household_payment_detail",
        "household_payment_detail_link",
        "import_session",
        "import_row",
        "merchant_reference_generation",
      ]) {
        destroy = true;
        await client.query(`CREATE TEMP TABLE ${table} (LIKE public.${table} INCLUDING DEFAULTS)`);
      }
      await client.query(
        `CREATE TEMP TABLE mart_net_worth_daily
         (LIKE analytics_marts.mart_net_worth_daily INCLUDING DEFAULTS)`,
      );
      await client.query(
        `INSERT INTO account (id, entity_id, provider, name, kind, currency)
         VALUES
           ($1::uuid, $1::uuid, 'gls', 'Synthetic EUR account', 'checking', 'EUR'),
           ($2::uuid, $2::uuid, 'manual', 'Synthetic manual account', 'checking', 'EUR'),
           ($3::uuid, $3::uuid, 'gls', 'Synthetic USD account', 'checking', 'USD')`,
        [account, manual, foreign],
      );
      await client.query(
        `INSERT INTO transaction (id, account_id, ts, value_date, kind, amount, counterparty)
         VALUES
           ($1::uuid, $4::uuid, '2026-06-01T10:00:00Z', '2026-06-01', 'payment', -10, 'Shop'),
           ($2::uuid, $5::uuid, '2026-06-01T10:00:00Z', '2026-06-01', 'payment', -10, 'Shop'),
           ($3::uuid, $6::uuid, '2026-06-01T10:00:00Z', '2026-06-01', 'payment', -10, 'Shop')`,
        [bankTx, manualTx, foreignTx, account, manual, foreign],
      );
      await client.query(
        `INSERT INTO household_classification
           (transaction_id, treatment, review_state, identity_confirmed, provenance,
            source_amount, source_currency, source_ts, source_counterparty, source_kind, explanation)
         SELECT t.id, 'expense', 'classified', false, 'manual', t.amount, a.currency, t.ts,
           t.counterparty, t.kind, 'synthetic'
         FROM transaction AS t INNER JOIN account AS a ON a.id = t.account_id`,
      );

      const context = { serverName: "postgres-test", serverVersion: "test" };
      const coverage = getSourceCoverageTool({
        runner: client,
        martTable: "pg_temp.mart_net_worth_daily",
        now: () => new Date("2026-10-04T08:00:00.000Z"),
      });
      const readCoverage = async () => {
        const out = await coverage.handler({ source_ids: ["paypal"] }, context);
        coverage.outputSchema.parse(out);
        return out;
      };
      const missing = await readCoverage();
      expect(missing.complete).toBe(false);
      expect(missing.sources[0]?.coverage).toMatchObject({
        completeness: "missing",
        freshness: "unknown",
        evidence_count: 0,
      });

      await client.query(
        `INSERT INTO household_payment_detail
           (id, provider, source_account_id, external_id, ts, amount, currency, event_kind,
            source_fields, revision, last_seen_at)
         VALUES ($1::uuid, 'paypal', 'synthetic', 'detail-1', '2026-06-01T09:00:00Z',
           -10, 'EUR', 'purchase', '{}'::jsonb, 1, '2026-09-01T00:00:00Z')`,
        [firstDetail],
      );
      const unlinked = await readCoverage();
      expect(unlinked.complete).toBe(false);
      expect(unlinked.sources[0]?.coverage).toMatchObject({
        completeness: "partial",
        freshness: "unknown",
        latest_observed_at: null,
        evidence_count: 1,
      });
      await client.query(
        `INSERT INTO household_payment_detail_link
           (transaction_id, detail_id, bank_amount, detail_revision)
         VALUES ($1::uuid, $3::uuid, -10, 1), ($2::uuid, $3::uuid, -10, 1)`,
        [manualTx, foreignTx, firstDetail],
      );
      expect((await readCoverage()).sources[0]?.coverage).toMatchObject({
        completeness: "partial",
        freshness: "unknown",
      });

      await client.query(
        `INSERT INTO household_payment_detail_link
           (transaction_id, detail_id, bank_amount, detail_revision)
         VALUES ($1::uuid, $2::uuid, -10, 1)`,
        [bankTx, firstDetail],
      );
      const linked = await readCoverage();
      expect(linked.complete).toBe(true);
      expect(linked.sources[0]?.coverage).toMatchObject({
        completeness: "complete",
        freshness: "stale",
        latest_observed_at: "2026-09-01T00:00:00.000Z",
      });

      await client.query(
        `INSERT INTO household_payment_detail
           (id, provider, source_account_id, external_id, ts, amount, currency, event_kind,
            source_fields, revision, last_seen_at)
         VALUES ($1::uuid, 'paypal', 'synthetic', 'detail-2', '2026-06-01T09:00:00Z',
           -10, 'EUR', 'purchase', '{}'::jsonb, 1, '2026-10-03T00:00:00Z')`,
        [secondDetail],
      );
      expect((await readCoverage()).sources[0]?.coverage).toMatchObject({
        completeness: "partial",
        freshness: "stale",
        latest_observed_at: "2026-09-01T00:00:00.000Z",
        evidence_count: 2,
      });
      await client.query(
        `INSERT INTO household_payment_detail_link
           (transaction_id, detail_id, bank_amount, detail_revision)
         VALUES ($1::uuid, $2::uuid, -10, 1)`,
        [bankTx, secondDetail],
      );
      expect((await readCoverage()).sources[0]?.coverage).toMatchObject({
        completeness: "complete",
        freshness: "fresh",
        latest_observed_at: "2026-10-03T00:00:00.000Z",
      });

      await client.query(
        `WITH inserted AS (
           INSERT INTO household_payment_detail
             (id, provider, source_account_id, external_id, ts, amount, currency, event_kind,
              source_fields, revision, last_seen_at)
           SELECT gen_random_uuid(), 'paypal', 'synthetic', 'extra-' || n::text,
             '2026-06-01T09:00:00Z'::timestamptz, -1, 'EUR', 'purchase',
             '{}'::jsonb, 1, '2026-10-03T00:00:00Z'::timestamptz
           FROM generate_series(1, 9) AS n
           RETURNING id
         )
         INSERT INTO household_payment_detail_link
           (transaction_id, detail_id, bank_amount, detail_revision)
         SELECT $1::uuid, id, -1, 1 FROM inserted`,
        [bankTx],
      );
      const overBound = await readCoverage();
      expect(overBound.complete).toBe(false);
      expect(overBound.sources[0]?.coverage).toMatchObject({
        completeness: "partial",
        freshness: "unknown",
        latest_observed_at: null,
        evidence_count: 11,
      });
      const detail = getHouseholdTransactionDetailTool({
        runner: {
          query: (sql, params) => client.query(sql, [...params]),
          readSnapshot: (operation) => operation(client),
        },
      });
      await expect(detail.handler({ transaction_id: bankTx }, context)).rejects.toThrow(
        "more linked PayPal detail",
      );
      await client.query(
        `DELETE FROM pg_temp.household_payment_detail_link
         WHERE detail_id IN (
           SELECT id FROM pg_temp.household_payment_detail WHERE external_id LIKE 'extra-%'
         )`,
      );
      await client.query(
        "DELETE FROM pg_temp.household_payment_detail WHERE external_id LIKE 'extra-%'",
      );
      await client.query(
        `WITH categories AS (
           INSERT INTO household_category (id, name, kind)
           SELECT gen_random_uuid(), 'Synthetic category ' || n::text, 'expense'
           FROM generate_series(1, 100) AS n
           RETURNING id
         )
         INSERT INTO household_allocation (transaction_id, category_id, amount)
         SELECT $1::uuid, id, -0.10 FROM categories`,
        [bankTx],
      );
      const bounded = await detail.handler({ transaction_id: bankTx }, context);
      detail.outputSchema.parse(bounded);
      expect(bounded.allocations).toHaveLength(100);
      expect(bounded.allocation_total).toBe("-10.0000");
      expect((await readCoverage()).sources[0]?.coverage.completeness).toBe("complete");

      await client.query(
        `WITH category AS (
           INSERT INTO household_category (id, name, kind)
           VALUES (gen_random_uuid(), 'Synthetic extra category', 'expense')
           RETURNING id
         )
         INSERT INTO household_allocation (transaction_id, category_id, amount)
         SELECT $1::uuid, id, 0 FROM category`,
        [bankTx],
      );
      await expect(detail.handler({ transaction_id: bankTx }, context)).rejects.toThrow(
        "more allocations",
      );
      expect((await readCoverage()).sources[0]?.coverage).toMatchObject({
        completeness: "partial",
        freshness: "unknown",
        evidence_count: 2,
      });
    } finally {
      client.release(destroy);
      await pool.end();
    }
  });
});

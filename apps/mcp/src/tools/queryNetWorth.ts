/**
 * MCP tool: `query_net_worth`.
 *
 * Returns aggregated daily net-worth rows from the dbt mart
 * `mart_net_worth_daily`. Aggregates only — never raw transactions or
 * account numbers. Output rows are summed across the household for the
 * requested currency, optionally broken down by account or asset class.
 *
 * Mart mapping (see `dbt/models/marts/mart_net_worth_daily.sql`):
 *   - Date column: `as_of` (DATE)
 *   - Currency columns: `balance_eur`, `balance_dkk` (NUMERIC)
 *   - Per-row grain: (entity, account, as_of)
 *
 * Breakdown semantics:
 *   - `none`         → one row per `as_of`, value = SUM across all accounts
 *   - `account`      → one row per (`as_of`, account_id), `breakdown_key`
 *                      = account UUID
 *   - `asset_class`  → one row per (`as_of`, account.kind), `breakdown_key`
 *                      = account.kind. The mart does not carry an
 *                      instrument-level asset_class column, so we map
 *                      `asset_class ≡ account.kind` from `public.account`
 *                      (e.g. `bank`, `brokerage`, `pension`, `cash`).
 *                      A future mart that exposes a true instrument
 *                      asset_class can replace this join without
 *                      changing the wire schema.
 */

import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * True iff `value` is a valid ISO `YYYY-MM-DD` calendar date. The
 * regex check rules out shapes like `2024-1-1`; the `Date.UTC`
 * round-trip rules out impossible dates like `2024-13-40` or
 * `2024-02-30` that would otherwise reach Postgres and surface as a
 * raw `invalid input syntax for type date` error.
 */
function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const [y, m, d] = value.split("-").map(Number) as [number, number, number];
  const ts = Date.UTC(y, m - 1, d);
  const round = new Date(ts);
  return round.getUTCFullYear() === y && round.getUTCMonth() === m - 1 && round.getUTCDate() === d;
}

const IsoDate = z.string().refine(isValidIsoDate, {
  message: "must be a valid ISO calendar date (YYYY-MM-DD)",
});

const InputSchema = z
  .object({
    date_range: z
      .object({
        from: IsoDate,
        to: IsoDate,
      })
      .strict()
      .refine((r) => r.from <= r.to, {
        message: "date_range.from must be on or before date_range.to",
        path: ["from"],
      }),
    currency: z.enum(["EUR", "DKK"]),
    breakdown_by: z.enum(["asset_class", "account", "none"]),
  })
  .strict();

export type QueryNetWorthInput = z.infer<typeof InputSchema>;

const OutputRowSchema = z
  .object({
    date: z.string().regex(ISO_DATE),
    currency: z.enum(["EUR", "DKK"]),
    breakdown_key: z.string().optional(),
    value: z.number().finite(),
  })
  .strict();

const OutputSchema = z.array(OutputRowSchema);

export type QueryNetWorthOutput = z.infer<typeof OutputSchema>;

/**
 * Minimal pg-compatible interface so unit tests can pass a fake without
 * needing a real `pg.Pool`. The real `pg.Pool` matches this shape.
 */
export interface NetWorthQueryRunner {
  query<R extends Record<string, unknown>>(
    sql: string,
    params: ReadonlyArray<unknown>,
  ): Promise<{ rows: R[] }>;
}

export interface QueryNetWorthOptions {
  runner: NetWorthQueryRunner;
  /**
   * Fully-qualified table name of the mart. Defaults to dbt's
   * `analytics_marts.mart_net_worth_daily`. If overridden, the value
   * MUST be a hard-coded constant or come from trusted config — it is
   * interpolated into SQL after a strict `schema.table` identifier
   * check, never user input.
   */
  martTable?: string;
  /**
   * Fully-qualified table name of the operational `account` table.
   * Defaults to `public.account`. Same trust rules as `martTable`.
   */
  accountTable?: string;
}

const QUALIFIED_IDENT = /^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$/;

function assertQualifiedIdent(value: string, label: string): void {
  if (!QUALIFIED_IDENT.test(value)) {
    throw new Error(
      `${label} must match ${QUALIFIED_IDENT.source} (lowercase schema.table identifier)`,
    );
  }
}

interface MartRow extends Record<string, unknown> {
  date: Date | string;
  breakdown_key: string | null;
  value: string | number | null;
}

function formatDate(value: Date | string): string {
  if (value instanceof Date) {
    return value.toISOString().slice(0, 10);
  }
  return String(value).slice(0, 10);
}

function buildSql(
  breakdownBy: QueryNetWorthInput["breakdown_by"],
  currency: QueryNetWorthInput["currency"],
  martTable: string,
  accountTable: string,
): string {
  const valueCol = currency === "EUR" ? "m.balance_eur" : "m.balance_dkk";

  if (breakdownBy === "none") {
    return `
      SELECT
        m.as_of AS date,
        NULL::text AS breakdown_key,
        SUM(${valueCol})::float8 AS value
      FROM ${martTable} AS m
      WHERE m.as_of >= $1::date AND m.as_of <= $2::date
      GROUP BY m.as_of
      ORDER BY m.as_of ASC
    `;
  }

  if (breakdownBy === "account") {
    return `
      SELECT
        m.as_of AS date,
        m.account_id::text AS breakdown_key,
        SUM(${valueCol})::float8 AS value
      FROM ${martTable} AS m
      WHERE m.as_of >= $1::date AND m.as_of <= $2::date
      GROUP BY m.as_of, m.account_id
      ORDER BY m.as_of ASC, m.account_id ASC
    `;
  }

  // asset_class → account.kind
  return `
    SELECT
      m.as_of AS date,
      a.kind AS breakdown_key,
      SUM(${valueCol})::float8 AS value
    FROM ${martTable} AS m
    INNER JOIN ${accountTable} AS a ON a.id = m.account_id
    WHERE m.as_of >= $1::date AND m.as_of <= $2::date
    GROUP BY m.as_of, a.kind
    ORDER BY m.as_of ASC, a.kind ASC
  `;
}

export function queryNetWorthTool(
  opts: QueryNetWorthOptions,
): ToolDefinition<QueryNetWorthInput, QueryNetWorthOutput> {
  const martTable = opts.martTable ?? "analytics_marts.mart_net_worth_daily";
  const accountTable = opts.accountTable ?? "public.account";
  assertQualifiedIdent(martTable, "martTable");
  assertQualifiedIdent(accountTable, "accountTable");

  return {
    name: "query_net_worth",
    description:
      "Aggregated daily net worth from `mart_net_worth_daily`. Returns one " +
      "row per date (and optional breakdown key) within `date_range`, valued " +
      "in `currency`. `breakdown_by` controls grouping: `none` sums across the " +
      "household, `account` groups by account UUID, `asset_class` groups by " +
      "`account.kind` (bank / brokerage / pension / cash). Aggregates only — " +
      "never returns transactions or account numbers.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const sql = buildSql(args.breakdown_by, args.currency, martTable, accountTable);
      const result = await opts.runner.query<MartRow>(sql, [
        args.date_range.from,
        args.date_range.to,
      ]);

      return result.rows.map((row) => {
        const date = formatDate(row.date);
        const value = typeof row.value === "string" ? Number(row.value) : (row.value ?? 0);
        const base = {
          date,
          currency: args.currency,
          value: Number(value),
        };
        if (args.breakdown_by === "none" || row.breakdown_key === null) {
          return base;
        }
        return { ...base, breakdown_key: row.breakdown_key };
      });
    },
  };
}

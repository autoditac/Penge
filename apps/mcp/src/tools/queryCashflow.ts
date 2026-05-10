/**
 * MCP tool: `query_cashflow`.
 *
 * Returns aggregated cashflow rows from the dbt mart
 * `mart_cashflow_daily`, rolled up to the requested granularity
 * (`day` / `week` / `month` / `year`). Aggregates only — never raw
 * transactions or account numbers.
 *
 * Mart mapping (see `dbt/models/marts/mart_cashflow_daily.sql`):
 *   - Date column: `as_of` (DATE, daily grain)
 *   - Currency columns: `inflow_eur` / `outflow_eur` / `net_eur` and
 *     `inflow_dkk` / `outflow_dkk` / `net_dkk` (NUMERIC)
 *   - Per-row grain: (account_id, as_of)
 *
 * Period semantics:
 *   - `period_start` / `period_end` are the inclusive bounds of the
 *     bucket clipped to the requested `date_range`. For example, a
 *     `month` bucket containing 2024-01 with `date_range.from =
 *     2024-01-15` will report `period_start = 2024-01-15`.
 *   - Days within the date_range that have no cashflow contribute
 *     nothing to a bucket; a bucket with zero activity is omitted
 *     entirely (the mart simply has no row for those days).
 */

import { z } from "zod";

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

const Granularity = z.enum(["day", "week", "month", "year"]);
const Currency = z.enum(["EUR", "DKK"]);

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
    granularity: Granularity,
    currency: Currency.optional(),
  })
  .strict();

export type QueryCashflowInput = z.infer<typeof InputSchema>;

const OutputRowSchema = z
  .object({
    period_start: z.string().regex(ISO_DATE),
    period_end: z.string().regex(ISO_DATE),
    currency: Currency,
    inflow: z.number().finite(),
    outflow: z.number().finite(),
    net: z.number().finite(),
  })
  .strict();

const OutputSchema = z.array(OutputRowSchema);

export type QueryCashflowOutput = z.infer<typeof OutputSchema>;

/**
 * Minimal pg-compatible interface so unit tests can pass a fake
 * without needing a real `pg.Pool`. The real `pg.Pool` matches this
 * shape.
 */
export interface CashflowQueryRunner {
  query<R extends Record<string, unknown>>(
    sql: string,
    params: ReadonlyArray<unknown>,
  ): Promise<{ rows: R[] }>;
}

export interface QueryCashflowOptions {
  runner: CashflowQueryRunner;
  /**
   * Fully-qualified table name of the mart. Defaults to dbt's
   * `analytics_marts.mart_cashflow_daily`. If overridden, the value
   * MUST be a hard-coded constant or come from trusted config — it is
   * interpolated into SQL after a strict `schema.table` identifier
   * check, never user input.
   */
  martTable?: string;
  /** Default currency when the request omits one. Defaults to EUR. */
  defaultCurrency?: z.infer<typeof Currency>;
}

const QUALIFIED_IDENT = /^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$/;

function assertQualifiedIdent(value: string, label: string): void {
  if (!QUALIFIED_IDENT.test(value)) {
    throw new Error(
      `${label} must match ${QUALIFIED_IDENT.source} (lowercase schema.table identifier)`,
    );
  }
}

interface BucketRow extends Record<string, unknown> {
  period_start: Date | string;
  period_end: Date | string;
  inflow: string | number | null;
  outflow: string | number | null;
  net: string | number | null;
}

function formatDate(value: Date | string): string {
  if (value instanceof Date) {
    return value.toISOString().slice(0, 10);
  }
  return String(value).slice(0, 10);
}

function toNumber(value: string | number | null): number {
  if (value === null) return 0;
  return typeof value === "string" ? Number(value) : value;
}

function buildSql(
  granularity: QueryCashflowInput["granularity"],
  currency: z.infer<typeof Currency>,
  martTable: string,
): string {
  const inflowCol = currency === "EUR" ? "m.inflow_eur" : "m.inflow_dkk";
  const outflowCol = currency === "EUR" ? "m.outflow_eur" : "m.outflow_dkk";
  const netCol = currency === "EUR" ? "m.net_eur" : "m.net_dkk";

  // `granularity` is a Zod-validated enum value, never user free-text.
  // It is still passed as a parameter ($3) to keep the SQL plan stable
  // and to satisfy the "no user input concatenated into SQL" rule.
  return `
    WITH bucket AS (
      SELECT
        date_trunc($3::text, m.as_of)::date AS bucket_start,
        (
          date_trunc($3::text, m.as_of)
          + ('1 ' || $3::text)::interval
          - interval '1 day'
        )::date AS bucket_end,
        ${inflowCol} AS inflow,
        ${outflowCol} AS outflow,
        ${netCol} AS net
      FROM ${martTable} AS m
      WHERE m.as_of >= $1::date AND m.as_of <= $2::date
    )
    SELECT
      GREATEST(bucket_start, $1::date) AS period_start,
      LEAST(bucket_end, $2::date) AS period_end,
      SUM(inflow)::float8 AS inflow,
      SUM(outflow)::float8 AS outflow,
      SUM(net)::float8 AS net
    FROM bucket
    GROUP BY bucket_start, bucket_end
    ORDER BY bucket_start ASC
  `;
}

export function queryCashflowTool(
  opts: QueryCashflowOptions,
): ToolDefinition<QueryCashflowInput, QueryCashflowOutput> {
  const martTable = opts.martTable ?? "analytics_marts.mart_cashflow_daily";
  const defaultCurrency = opts.defaultCurrency ?? "EUR";
  assertQualifiedIdent(martTable, "martTable");

  return {
    name: "query_cashflow",
    description:
      "Aggregated cashflow from `mart_cashflow_daily`, rolled up to the " +
      "requested granularity (`day` / `week` / `month` / `year`). Returns " +
      "one row per period within `date_range` with summed `inflow`, " +
      "`outflow`, and `net` valued in `currency` (defaults to EUR). Period " +
      "bounds are clipped to the requested range. Aggregates only — never " +
      "returns transactions or account numbers.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const currency = args.currency ?? defaultCurrency;
      const sql = buildSql(args.granularity, currency, martTable);
      const result = await opts.runner.query<BucketRow>(sql, [
        args.date_range.from,
        args.date_range.to,
        args.granularity,
      ]);

      return result.rows.map((row) => ({
        period_start: formatDate(row.period_start),
        period_end: formatDate(row.period_end),
        currency,
        inflow: Number(toNumber(row.inflow)),
        outflow: Number(toNumber(row.outflow)),
        net: Number(toNumber(row.net)),
      }));
    },
  };
}

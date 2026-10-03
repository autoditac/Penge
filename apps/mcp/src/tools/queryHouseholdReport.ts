/**
 * MCP tool: `query_household_report`.
 *
 * Returns exact Decimal-string aggregates from the household reporting mart.
 * It intentionally never returns bank transactions, payment detail, account
 * identifiers, or provider payloads.
 */

import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DECIMAL = /^-?\d+(?:\.\d+)?$/;
const SCALE = 8;
const SCALE_FACTOR = 10n ** BigInt(SCALE);

function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number) as [number, number, number];
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

const IsoDate = z.string().refine(isValidIsoDate, {
  message: "must be a valid ISO calendar date (YYYY-MM-DD)",
});
const Uuid = z.string().regex(UUID, "must be a UUID");
const UniqueUuids = z
  .array(Uuid)
  .max(50)
  .refine((ids) => new Set(ids).size === ids.length, {
    message: "values must be unique",
  });

const InputSchema = z
  .object({
    date_range: z
      .object({ from: IsoDate, to: IsoDate })
      .strict()
      .refine((range) => range.from <= range.to, {
        message: "date_range.from must be on or before date_range.to",
        path: ["from"],
      }),
    granularity: z.enum(["day", "month", "year"]),
    account_ids: UniqueUuids.optional(),
    entity_ids: UniqueUuids.optional(),
    category_id: Uuid.optional(),
  })
  .strict()
  .refine(
    (input) =>
      (Date.parse(`${input.date_range.to}T00:00:00Z`) -
        Date.parse(`${input.date_range.from}T00:00:00Z`)) /
        86_400_000 <
      4000,
    {
      message: "date_range must contain at most 4000 days",
      path: ["date_range"],
    },
  );

export type QueryHouseholdReportInput = z.infer<typeof InputSchema>;

const CurrencyAmountSchema = z
  .object({
    amount: z.string().regex(DECIMAL).nullable(),
    known_subtotal: z.string().regex(DECIMAL),
    complete: z.boolean(),
    missing_count: z.number().int().nonnegative(),
  })
  .strict();

const CurrencyPairSchema = z
  .object({
    eur: CurrencyAmountSchema,
    dkk: CurrencyAmountSchema,
  })
  .strict();

const TotalsSchema = z
  .object({
    income: CurrencyPairSchema,
    gross_expenses: CurrencyPairSchema,
    refunds: CurrencyPairSchema,
    net_expenses: CurrencyPairSchema,
    surplus: CurrencyPairSchema,
  })
  .strict();

const OutputSchema = z
  .object({
    date_range: z.object({ from: IsoDate, to: IsoDate }).strict(),
    granularity: z.enum(["day", "month", "year"]),
    current: z.object({ since: IsoDate, until: IsoDate, totals: TotalsSchema }).strict(),
    previous: z.object({ since: IsoDate, until: IsoDate, totals: TotalsSchema }).strict(),
    change: TotalsSchema,
    trend: z
      .array(
        z
          .object({
            period_start: IsoDate,
            period_end: IsoDate,
            totals: TotalsSchema,
          })
          .strict(),
      )
      .max(4000),
  })
  .strict();

export type QueryHouseholdReportOutput = z.infer<typeof OutputSchema>;

export interface HouseholdReportQueryRunner {
  query<R extends Record<string, unknown>>(
    sql: string,
    params: ReadonlyArray<unknown>,
  ): Promise<{ rows: R[] }>;
}

export interface QueryHouseholdReportOptions {
  runner: HouseholdReportQueryRunner;
}

interface MartRow extends Record<string, unknown> {
  as_of: Date | string;
  treatment: "income" | "expense" | "refund" | "unclassified";
  known_allocation_amount_eur: string;
  known_allocation_amount_dkk: string;
  missing_fx_count_eur: string | number;
  missing_fx_count_dkk: string | number;
}

interface AmountAccumulator {
  known: bigint;
  missing: number;
}

interface MetricAccumulator {
  eur: AmountAccumulator;
  dkk: AmountAccumulator;
}

interface TotalsAccumulator {
  income: MetricAccumulator;
  gross_expenses: MetricAccumulator;
  refunds: MetricAccumulator;
}

const REPORT_SQL = `
  WITH RECURSIVE category_scope(category_id) AS (
    SELECT c.category_id
    FROM analytics_staging.stg_raw__household_category AS c
    WHERE c.category_id = $6::uuid
    UNION
    SELECT child.category_id
    FROM analytics_staging.stg_raw__household_category AS child
    INNER JOIN category_scope AS parent ON child.parent_id = parent.category_id
  )
  SELECT
    m.as_of,
    m.treatment,
    m.allocation_known_amount_eur::text AS known_allocation_amount_eur,
    m.allocation_known_amount_dkk::text AS known_allocation_amount_dkk,
    m.missing_fx_count_eur,
    m.missing_fx_count_dkk
  FROM analytics_marts.mart_household_report_daily AS m
  WHERE m.is_default_scope
    AND (
      m.as_of BETWEEN $1::date AND $2::date
      OR m.as_of BETWEEN $3::date AND $4::date
    )
    AND ($7::uuid[] IS NULL OR m.account_id = ANY($7::uuid[]))
    AND ($8::uuid[] IS NULL OR m.entity_id = ANY($8::uuid[]))
    AND (
      $6::uuid IS NULL
      OR m.category_id IN (SELECT category_id FROM category_scope)
    )
  ORDER BY m.as_of, m.treatment, m.category_id NULLS FIRST
`;

const CHECK_ACCOUNTS_SQL = `
  SELECT count(*)::int AS count
  FROM public.account
  WHERE id = ANY($1::uuid[])
    AND kind = 'checking'
    AND ($2::uuid[] IS NULL OR entity_id = ANY($2::uuid[]))
`;

const CHECK_CATEGORY_SQL = `
  SELECT EXISTS (
    SELECT 1
    FROM analytics_staging.stg_raw__household_category
    WHERE category_id = $1::uuid
  ) AS found
`;

function parseDate(value: Date | string): string {
  return value instanceof Date ? value.toISOString().slice(0, 10) : String(value).slice(0, 10);
}

function parseDecimal(value: unknown): bigint {
  if (typeof value !== "string" || !DECIMAL.test(value)) {
    throw new Error("household report mart returned a non-decimal amount");
  }
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction = ""] = unsigned.split(".");
  if (whole === undefined) {
    throw new Error("household report mart returned a malformed decimal amount");
  }
  if (fraction.length > SCALE) {
    throw new Error(`household report amount exceeds ${SCALE} decimal places`);
  }
  const scaled = BigInt(whole) * SCALE_FACTOR + BigInt(fraction.padEnd(SCALE, "0") || "0");
  return negative ? -scaled : scaled;
}

function formatDecimal(value: bigint): string {
  const negative = value < 0n;
  const absolute = negative ? -value : value;
  const whole = absolute / SCALE_FACTOR;
  const fraction = (absolute % SCALE_FACTOR).toString().padStart(SCALE, "0").replace(/0+$/, "");
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}

function emptyMetric(): MetricAccumulator {
  return {
    eur: { known: 0n, missing: 0 },
    dkk: { known: 0n, missing: 0 },
  };
}

function emptyTotals(): TotalsAccumulator {
  return {
    income: emptyMetric(),
    gross_expenses: emptyMetric(),
    refunds: emptyMetric(),
  };
}

function addRow(totals: TotalsAccumulator, row: MartRow): void {
  const metric =
    row.treatment === "income"
      ? totals.income
      : row.treatment === "refund"
        ? totals.refunds
        : totals.gross_expenses;
  const eurAmount = parseDecimal(row.known_allocation_amount_eur);
  const dkkAmount = parseDecimal(row.known_allocation_amount_dkk);
  metric.eur.known +=
    row.treatment === "expense" || row.treatment === "unclassified"
      ? absolute(eurAmount)
      : eurAmount;
  metric.dkk.known +=
    row.treatment === "expense" || row.treatment === "unclassified"
      ? absolute(dkkAmount)
      : dkkAmount;
  metric.eur.missing += Number(row.missing_fx_count_eur);
  metric.dkk.missing += Number(row.missing_fx_count_dkk);
}

function absolute(value: bigint): bigint {
  return value < 0n ? -value : value;
}

function currencyAmount(value: AmountAccumulator): z.infer<typeof CurrencyAmountSchema> {
  return {
    amount: value.missing === 0 ? formatDecimal(value.known) : null,
    known_subtotal: formatDecimal(value.known),
    complete: value.missing === 0,
    missing_count: value.missing,
  };
}

function subtractAmount(left: AmountAccumulator, right: AmountAccumulator): AmountAccumulator {
  return {
    known: left.known - right.known,
    missing: left.missing + right.missing,
  };
}

function reportTotals(
  accumulator: TotalsAccumulator,
): QueryHouseholdReportOutput["current"]["totals"] {
  const net = {
    eur: subtractAmount(accumulator.gross_expenses.eur, accumulator.refunds.eur),
    dkk: subtractAmount(accumulator.gross_expenses.dkk, accumulator.refunds.dkk),
  };
  const surplus = {
    eur: subtractAmount(accumulator.income.eur, net.eur),
    dkk: subtractAmount(accumulator.income.dkk, net.dkk),
  };
  return {
    income: {
      eur: currencyAmount(accumulator.income.eur),
      dkk: currencyAmount(accumulator.income.dkk),
    },
    gross_expenses: {
      eur: currencyAmount(accumulator.gross_expenses.eur),
      dkk: currencyAmount(accumulator.gross_expenses.dkk),
    },
    refunds: {
      eur: currencyAmount(accumulator.refunds.eur),
      dkk: currencyAmount(accumulator.refunds.dkk),
    },
    net_expenses: { eur: currencyAmount(net.eur), dkk: currencyAmount(net.dkk) },
    surplus: { eur: currencyAmount(surplus.eur), dkk: currencyAmount(surplus.dkk) },
  };
}

function subtractTotals(
  left: TotalsAccumulator,
  right: TotalsAccumulator,
): QueryHouseholdReportOutput["change"] {
  const difference = emptyTotals();
  for (const key of ["income", "gross_expenses", "refunds"] as const) {
    difference[key].eur = subtractAmount(left[key].eur, right[key].eur);
    difference[key].dkk = subtractAmount(left[key].dkk, right[key].dkk);
  }
  return reportTotals(difference);
}

function bucketStart(value: string, granularity: QueryHouseholdReportInput["granularity"]): string {
  const [year, month] = value.split("-").map(Number) as [number, number];
  if (granularity === "year") return `${year.toString().padStart(4, "0")}-01-01`;
  if (granularity === "month") {
    return `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}-01`;
  }
  return value;
}

function nextBucketStart(
  value: string,
  granularity: QueryHouseholdReportInput["granularity"],
): string {
  const [year, month, day] = value.split("-").map(Number) as [number, number, number];
  const next =
    granularity === "year"
      ? new Date(Date.UTC(year + 1, 0, 1))
      : granularity === "month"
        ? new Date(Date.UTC(year, month, 1))
        : new Date(Date.UTC(year, month - 1, day + 1));
  return next.toISOString().slice(0, 10);
}

function addDays(value: string, days: number): string {
  const [year, month, day] = value.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

function previousRange(from: string, to: string): { from: string; to: string } {
  const duration =
    (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000 + 1;
  return { from: addDays(from, -duration), to: addDays(from, -1) };
}

function trendBuckets(
  from: string,
  to: string,
  granularity: QueryHouseholdReportInput["granularity"],
): Array<{ period_start: string; period_end: string; start: string }> {
  const buckets = [];
  let start = bucketStart(from, granularity);
  while (start <= to) {
    const end = addDays(nextBucketStart(start, granularity), -1);
    buckets.push({
      period_start: start < from ? from : start,
      period_end: end > to ? to : end,
      start,
    });
    start = nextBucketStart(start, granularity);
  }
  return buckets;
}

export function queryHouseholdReportTool(
  opts: QueryHouseholdReportOptions,
): ToolDefinition<QueryHouseholdReportInput, QueryHouseholdReportOutput> {
  return {
    name: "query_household_report",
    description:
      "Returns household income, expenses, refunds, surplus, comparison, and trend from the " +
      "bank-ledger reporting mart. Both EUR and DKK values remain exact decimal strings; " +
      "missing FX is null with its known subtotal and missing count. Aggregates only — no " +
      "transactions, account identifiers, or payment-provider payloads.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const previous = previousRange(args.date_range.from, args.date_range.to);
      const accountIds = args.account_ids ?? null;
      const entityIds = args.entity_ids ?? null;
      if (accountIds !== null) {
        const checked = await opts.runner.query<{ count: number }>(CHECK_ACCOUNTS_SQL, [
          accountIds,
          entityIds,
        ]);
        if (checked.rows[0]?.count !== accountIds.length) {
          throw new Error("account_ids must contain only checking accounts");
        }
      }
      if (args.category_id !== undefined) {
        const checked = await opts.runner.query<{ found: boolean }>(CHECK_CATEGORY_SQL, [
          args.category_id,
        ]);
        if (checked.rows[0]?.found !== true) {
          throw new Error("category_id does not identify a household category");
        }
      }
      const result = await opts.runner.query<MartRow>(REPORT_SQL, [
        args.date_range.from,
        args.date_range.to,
        previous.from,
        previous.to,
        args.granularity,
        args.category_id ?? null,
        accountIds,
        entityIds,
      ]);
      const current = emptyTotals();
      const prior = emptyTotals();
      const trend = new Map<string, TotalsAccumulator>();
      for (const row of result.rows) {
        const asOf = parseDate(row.as_of);
        const target = asOf >= args.date_range.from && asOf <= args.date_range.to ? current : prior;
        addRow(target, row);
        if (target === current) {
          const bucket = bucketStart(asOf, args.granularity);
          const totals = trend.get(bucket) ?? emptyTotals();
          addRow(totals, row);
          trend.set(bucket, totals);
        }
      }
      const points = trendBuckets(args.date_range.from, args.date_range.to, args.granularity).map(
        (bucket) => ({
          period_start: bucket.period_start,
          period_end: bucket.period_end,
          totals: reportTotals(trend.get(bucket.start) ?? emptyTotals()),
        }),
      );
      return {
        date_range: args.date_range,
        granularity: args.granularity,
        current: {
          since: args.date_range.from,
          until: args.date_range.to,
          totals: reportTotals(current),
        },
        previous: {
          since: previous.from,
          until: previous.to,
          totals: reportTotals(prior),
        },
        change: subtractTotals(current, prior),
        trend: points,
      };
    },
  };
}

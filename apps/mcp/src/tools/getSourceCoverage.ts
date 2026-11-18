import { z } from "zod/v3";

import { ToolDataError } from "../errors.js";
import type { ToolDefinition } from "../registry.js";
import {
  SOURCE_ALLOWLIST,
  SOURCE_CATALOG,
  MCP_READ_ONLY_TOOL_ALLOWLIST,
  HOUSEHOLD_TRANSACTION_PROVIDERS,
  MAX_LINKED_PAYPAL_DETAILS,
  MAX_TRANSACTION_ALLOCATIONS,
  SourceCatalogEntrySchema,
  SourceIdSchema,
  type SourceId,
} from "../sources.js";

const ObservationRowSchema = z
  .object({
    source_id: SourceIdSchema,
    account_count: z.coerce.number().int().nonnegative(),
    transaction_count: z.coerce.number().int().nonnegative(),
    holding_count: z.coerce.number().int().nonnegative(),
    evidence_count: z.coerce.number().int().nonnegative(),
    inaccessible_evidence_count: z.coerce.number().int().nonnegative(),
    latest_observed_at: z.union([z.date(), z.string()]).nullable(),
  })
  .strict();

const InputSchema = z
  .object({
    source_ids: z
      .array(SourceIdSchema)
      .max(SOURCE_ALLOWLIST.length)
      .refine((ids) => new Set(ids).size === ids.length, {
        message: "source_ids must be unique",
      })
      .optional(),
  })
  .strict();

const CoverageSchema = z
  .object({
    completeness: z.enum(["complete", "partial", "missing"]),
    freshness: z.enum(["fresh", "stale", "unknown"]),
    latest_observed_at: z.string().datetime().nullable(),
    stale_after_days: z.number().int().positive(),
    account_count: z.number().int().nonnegative(),
    transaction_count: z.number().int().nonnegative(),
    holding_count: z.number().int().nonnegative(),
    evidence_count: z.number().int().nonnegative(),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    transport: z.literal("stdio"),
    read_only: z.literal(true),
    source_allowlist: z.array(SourceIdSchema).length(SOURCE_ALLOWLIST.length),
    tool_allowlist: z.array(z.string().min(1)).length(MCP_READ_ONLY_TOOL_ALLOWLIST.length),
    sources: z
      .array(
        SourceCatalogEntrySchema.omit({ stale_after_days: true }).extend({
          coverage: CoverageSchema,
        }),
      )
      .max(SOURCE_ALLOWLIST.length),
    complete: z.boolean(),
  })
  .strict();

export type GetSourceCoverageInput = z.infer<typeof InputSchema>;
export type GetSourceCoverageOutput = z.infer<typeof OutputSchema>;

export interface SourceCoverageQueryRunner {
  query<R extends Record<string, unknown>>(
    sql: string,
    params: ReadonlyArray<unknown>,
  ): Promise<{ rows: R[] }>;
}

export interface GetSourceCoverageOptions {
  runner: SourceCoverageQueryRunner;
  now?: () => Date;
  /** Trusted schema-qualified net-worth mart name, overridable for isolated tests. */
  martTable?: string;
}

const QUALIFIED_IDENT = /^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$/;

function coverageSql(martTable: string): string {
  if (!QUALIFIED_IDENT.test(martTable)) {
    throw new ToolDataError("source coverage mart table must be a schema-qualified identifier");
  }
  return `
  WITH account_counts AS (
    SELECT a.provider, count(*)::int AS account_count,
      count(*) FILTER (WHERE NOT EXISTS (
        SELECT 1 FROM holding_snapshot AS h WHERE h.account_id = a.id
      ))::int AS missing_holding_count
    FROM account AS a
    WHERE a.provider = ANY($1::text[])
    GROUP BY a.provider
  ),
  transaction_counts AS (
    SELECT a.provider, count(*)::int AS transaction_count,
      max(t.created_at) AS latest_transaction_at,
      count(*) FILTER (
        WHERE a.provider = ANY($3::text[]) AND a.currency NOT IN ('EUR', 'DKK')
      )::int AS inaccessible_count
    FROM transaction AS t
    INNER JOIN account AS a ON a.id = t.account_id
    WHERE a.provider = ANY($1::text[])
    GROUP BY a.provider
  ),
  latest_holding_positions AS (
    SELECT DISTINCT ON (h.account_id, h.instrument_id)
      h.account_id, h.instrument_id, h.as_of, h.market_value::numeric(20, 4) AS value
    FROM holding_snapshot AS h
    INNER JOIN account AS a ON a.id = h.account_id
    WHERE a.provider = ANY($1::text[])
    ORDER BY h.account_id, h.instrument_id, h.as_of DESC
  ),
  latest_holding_accounts AS (
    -- The net-worth mart values a NULL market_value as 0, so an unvalued latest
    -- position must not be able to satisfy the balance match below.
    SELECT account_id, max(as_of) AS as_of, sum(value)::numeric(20, 4) AS expected_balance,
      bool_or(value IS NULL) AS has_unvalued_position
    FROM latest_holding_positions
    GROUP BY account_id
  ),
  holding_account_access AS (
    SELECT h.account_id,
      count(m.account_id) = 1 AND bool_and(
        NOT h.has_unvalued_position
        AND m.entity_id = a.entity_id AND m.account_currency = a.currency
        AND m.balance_acct_ccy = h.expected_balance
        AND m.balance_eur IS NOT NULL AND m.balance_dkk IS NOT NULL
      ) AS accessible
    FROM latest_holding_accounts AS h
    INNER JOIN account AS a ON a.id = h.account_id
    LEFT JOIN ${martTable} AS m ON m.account_id = h.account_id AND m.as_of = h.as_of
    GROUP BY h.account_id, h.expected_balance, h.has_unvalued_position, a.entity_id, a.currency
  ),
  holding_counts AS (
    SELECT a.provider, count(*)::int AS holding_count, max(h.created_at) AS latest_holding_at,
      count(DISTINCT h.account_id) FILTER (WHERE access.accessible IS NOT TRUE)::int AS inaccessible_count
    FROM holding_snapshot AS h
    INNER JOIN account AS a ON a.id = h.account_id
    INNER JOIN holding_account_access AS access ON access.account_id = h.account_id
    WHERE a.provider = ANY($1::text[])
    GROUP BY a.provider
  ),
  nordnet_import_observations AS (
    SELECT
      max(s.committed_at) FILTER (WHERE s.source = 'nordnet_transactions') AS latest_transaction_at,
      max(s.committed_at) FILTER (WHERE s.source = 'nordnet_holdings') AS latest_holding_at
    FROM import_session AS s
    INNER JOIN import_row AS r ON r.session_id = s.id
    INNER JOIN account AS a ON a.provider = 'nordnet'
      AND a.external_id = CASE
        WHEN s.source = 'nordnet_transactions' AND r.kind = 'transaction'
          THEN r.payload ->> 'account_number'
        WHEN s.source = 'nordnet_holdings' AND r.kind = 'holding'
          THEN s.params ->> 'account_number'
      END
    WHERE s.status = 'committed' AND s.committed_at IS NOT NULL AND NOT r.excluded
  ),
  nordnet_empty_holding_observations AS (
    SELECT max(s.committed_at) AS latest_holding_at
    FROM import_session AS s
    INNER JOIN account AS a ON a.provider = 'nordnet'
      AND a.external_id = s.params ->> 'account_number'
    WHERE s.source = 'nordnet_holdings' AND s.status = 'committed'
      AND s.committed_at IS NOT NULL AND s.params ->> 'empty_snapshot_confirmed' = 'true'
      AND NOT EXISTS (SELECT 1 FROM import_row AS r WHERE r.session_id = s.id)
  ),
  account_sources AS (
    SELECT
      accounts.provider AS source_id,
      accounts.account_count,
      coalesce(transactions.transaction_count, 0)::int AS transaction_count,
      coalesce(holdings.holding_count, 0)::int AS holding_count,
      (accounts.missing_holding_count + coalesce(transactions.inaccessible_count, 0) +
        coalesce(holdings.inaccessible_count, 0))::int AS inaccessible_evidence_count,
      CASE
        WHEN accounts.missing_holding_count > 0
          OR coalesce(transactions.inaccessible_count, 0) > 0
          OR coalesce(holdings.inaccessible_count, 0) > 0 THEN NULL
        WHEN accounts.provider = ANY($3::text[])
          THEN CASE
            WHEN transactions.latest_transaction_at IS NULL OR holdings.latest_holding_at IS NULL
              THEN NULL
            WHEN accounts.provider = 'nordnet'
              THEN least(
                greatest(transactions.latest_transaction_at, imports.latest_transaction_at),
                greatest(holdings.latest_holding_at, imports.latest_holding_at, empty_holding.latest_holding_at)
              )
            ELSE least(transactions.latest_transaction_at, holdings.latest_holding_at)
          END
        WHEN accounts.provider = 'manual'
          THEN holdings.latest_holding_at
        ELSE transactions.latest_transaction_at
      END AS latest_observed_at
    FROM account_counts AS accounts
    LEFT JOIN transaction_counts AS transactions ON transactions.provider = accounts.provider
    LEFT JOIN holding_counts AS holdings ON holdings.provider = accounts.provider
    CROSS JOIN nordnet_import_observations AS imports
    CROSS JOIN nordnet_empty_holding_observations AS empty_holding
  ),
  paypal_link_counts AS (
    SELECT link.transaction_id, count(*)::int AS detail_count
    FROM household_payment_detail_link AS link
    INNER JOIN household_payment_detail AS detail ON detail.id = link.detail_id
    WHERE detail.provider = 'paypal'
    GROUP BY link.transaction_id
  ),
  paypal_observations AS (
    SELECT detail.last_seen_at, EXISTS (
      SELECT 1
      FROM household_payment_detail_link AS link
      INNER JOIN transaction AS t ON t.id = link.transaction_id
      INNER JOIN account AS a ON a.id = t.account_id
      INNER JOIN paypal_link_counts AS counts ON counts.transaction_id = link.transaction_id
      WHERE link.detail_id = detail.id
        AND a.provider = ANY($3::text[])
        AND a.currency IN ('EUR', 'DKK')
        AND counts.detail_count <= ${MAX_LINKED_PAYPAL_DETAILS}
        AND NOT EXISTS (
          SELECT 1 FROM household_allocation AS allocation
          WHERE allocation.transaction_id = t.id
          LIMIT 1 OFFSET ${MAX_TRANSACTION_ALLOCATIONS}
        )
    ) AS accessible
    FROM household_payment_detail AS detail
    WHERE detail.provider = 'paypal'
  ),
  observations(source_id, account_count, transaction_count, holding_count, evidence_count, latest_observed_at, inaccessible_evidence_count) AS (
    SELECT CASE WHEN source_id = 'manual' THEN 'manual_facts' ELSE source_id END,
      account_count, transaction_count, holding_count,
      transaction_count + holding_count, latest_observed_at, inaccessible_evidence_count
    FROM account_sources

    UNION ALL
    SELECT 'ecb_fx', 0, 0, 0, count(*)::int, max(as_of)::timestamptz, 0 FROM fx_rate
      WHERE base_ccy = 'EUR' AND quote_ccy = 'DKK'
    UNION ALL
    SELECT 'household_classification', 0, count(*)::int, 0,
      (SELECT count(*)::int FROM household_allocation),
      (SELECT max(created_at) FROM household_audit), 0
    FROM household_classification
    UNION ALL
    SELECT 'paypal', 0, 0, 0, count(*)::int,
      max(last_seen_at) FILTER (WHERE accessible),
      count(*) FILTER (WHERE NOT accessible)::int
    FROM paypal_observations
    UNION ALL
    SELECT 'nsi_merchant_reference', 0, 0, 0, coalesce(max(record_count), 0)::int,
      max(completed_at), 0
    FROM merchant_reference_generation
    WHERE status = 'active' AND source_id = 'name-suggestion-index'
  )
  SELECT requested.source_id, coalesce(o.account_count, 0)::int AS account_count,
    coalesce(o.transaction_count, 0)::int AS transaction_count,
    coalesce(o.holding_count, 0)::int AS holding_count,
    coalesce(o.evidence_count, 0)::int AS evidence_count, o.latest_observed_at,
    coalesce(o.inaccessible_evidence_count, 0)::int AS inaccessible_evidence_count
  FROM unnest($2::text[]) AS requested(source_id)
  LEFT JOIN observations AS o ON o.source_id = requested.source_id
  ORDER BY requested.source_id
`;
}

function iso(value: Date | string | null): string | null {
  if (value === null) return null;
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    throw new ToolDataError("source coverage query returned an invalid observation timestamp");
  }
  return parsed.toISOString();
}

/** Enable Banking is the transport for these sources; it is never observed on its own. */
const ENABLE_BANKING_CONSTITUENTS = [
  "gls",
  "ebank",
  "lunar",
] as const satisfies readonly SourceId[];

type Coverage = z.infer<typeof CoverageSchema>;
const TRANSACTION_SOURCES: readonly SourceId[] = HOUSEHOLD_TRANSACTION_PROVIDERS;

function completeness(sourceId: SourceId, row: z.infer<typeof ObservationRowSchema>) {
  if (
    row.evidence_count === 0 &&
    row.account_count === 0 &&
    row.transaction_count === 0 &&
    row.holding_count === 0
  ) {
    return "missing" as const;
  }
  if (row.inaccessible_evidence_count > 0) {
    return "partial" as const;
  }
  if (
    TRANSACTION_SOURCES.includes(sourceId) &&
    (row.account_count === 0 || row.transaction_count === 0 || row.holding_count === 0)
  ) {
    return "partial" as const;
  }
  if (sourceId === "manual_facts" && (row.account_count === 0 || row.holding_count === 0)) {
    return "partial" as const;
  }
  if (
    sourceId === "household_classification" &&
    (row.transaction_count === 0 || row.evidence_count === 0)
  ) {
    return "partial" as const;
  }
  return "complete" as const;
}

export function getSourceCoverageTool(
  opts: GetSourceCoverageOptions,
): ToolDefinition<GetSourceCoverageInput, GetSourceCoverageOutput> {
  const sql = coverageSql(opts.martTable ?? "analytics_marts.mart_net_worth_daily");
  return {
    name: "get_source_coverage",
    description:
      "Return the typed source catalog with observed freshness, completeness, capabilities, and source-to-tool evidence mappings.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const requested = args.source_ids ?? [...SOURCE_ALLOWLIST];
      const observed = [
        ...new Set(
          requested.flatMap((sourceId) =>
            sourceId === "enable_banking" ? [...ENABLE_BANKING_CONSTITUENTS] : [sourceId],
          ),
        ),
      ];
      const providers = ["gls", "ebank", "lunar", "nordnet", "pfa", "growney", "manual"];
      const result = await opts.runner.query(sql, [
        providers,
        observed,
        HOUSEHOLD_TRANSACTION_PROVIDERS,
      ]);
      const observations = new Map(
        result.rows.map((raw) => {
          const row = ObservationRowSchema.parse(raw);
          return [row.source_id, row] as const;
        }),
      );
      const now = opts.now?.() ?? new Date();
      const catalogEntry = (sourceId: SourceId) => {
        const catalog = SOURCE_CATALOG.find((entry) => entry.id === sourceId);
        if (!catalog) throw new ToolDataError(`catalog entry missing for ${sourceId}`);
        return catalog;
      };
      const freshnessOf = (latest: string | null, staleAfterDays: number) => {
        if (latest === null) return "unknown" as const;
        return now.valueOf() - Date.parse(latest) <= staleAfterDays * 86_400_000
          ? ("fresh" as const)
          : ("stale" as const);
      };
      const observedCoverage = (sourceId: SourceId): Coverage => {
        const observation =
          observations.get(sourceId) ??
          ObservationRowSchema.parse({
            source_id: sourceId,
            account_count: 0,
            transaction_count: 0,
            holding_count: 0,
            evidence_count: 0,
            inaccessible_evidence_count: 0,
            latest_observed_at: null,
          });
        const latest = iso(observation.latest_observed_at);
        if (latest !== null && Date.parse(latest) > now.valueOf() + 300_000) {
          throw new ToolDataError(`source ${sourceId} returned a future observation timestamp`);
        }
        const staleAfterDays = catalogEntry(sourceId).stale_after_days;
        return {
          completeness: completeness(sourceId, observation),
          freshness: freshnessOf(latest, staleAfterDays),
          latest_observed_at: latest,
          stale_after_days: staleAfterDays,
          account_count: observation.account_count,
          transaction_count: observation.transaction_count,
          holding_count: observation.holding_count,
          evidence_count: observation.evidence_count,
        };
      };
      // The aggregate is only as complete and fresh as its weakest constituent bank.
      const enableBankingCoverage = (): Coverage => {
        const parts = ENABLE_BANKING_CONSTITUENTS.map(observedCoverage);
        const latests = parts.map((part) => part.latest_observed_at);
        const latest = latests.some((value) => value === null)
          ? null
          : (latests as string[]).reduce((oldest, value) =>
              Date.parse(value) < Date.parse(oldest) ? value : oldest,
            );
        const staleAfterDays = catalogEntry("enable_banking").stale_after_days;
        const sum = (
          key: "account_count" | "transaction_count" | "holding_count" | "evidence_count",
        ) => parts.reduce((total, part) => total + part[key], 0);
        return {
          completeness: parts.every((part) => part.completeness === "complete")
            ? "complete"
            : parts.every((part) => part.completeness === "missing")
              ? "missing"
              : "partial",
          freshness: freshnessOf(latest, staleAfterDays),
          latest_observed_at: latest,
          stale_after_days: staleAfterDays,
          account_count: sum("account_count"),
          transaction_count: sum("transaction_count"),
          holding_count: sum("holding_count"),
          evidence_count: sum("evidence_count"),
        };
      };
      const sources = requested.map((sourceId) => {
        const { stale_after_days: _staleAfterDays, ...metadata } = catalogEntry(sourceId);
        return {
          ...metadata,
          coverage:
            sourceId === "enable_banking" ? enableBankingCoverage() : observedCoverage(sourceId),
        };
      });
      return {
        generated_at: now.toISOString(),
        transport: "stdio",
        read_only: true,
        source_allowlist: [...SOURCE_ALLOWLIST],
        tool_allowlist: [...MCP_READ_ONLY_TOOL_ALLOWLIST],
        sources,
        complete:
          sources.length > 0 &&
          sources.every((source) => source.coverage.completeness === "complete"),
      };
    },
  };
}

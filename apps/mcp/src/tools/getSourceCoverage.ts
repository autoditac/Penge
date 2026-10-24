import { z } from "zod/v3";

import { ToolDataError } from "../errors.js";
import type { ToolDefinition } from "../registry.js";
import {
  SOURCE_ALLOWLIST,
  SOURCE_CATALOG,
  MCP_READ_ONLY_TOOL_ALLOWLIST,
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
}

const COVERAGE_SQL = `
  WITH account_counts AS (
    SELECT provider, count(*)::int AS account_count
    FROM account
    WHERE provider = ANY($1::text[])
    GROUP BY provider
  ),
  transaction_counts AS (
    SELECT a.provider, count(*)::int AS transaction_count, max(t.created_at) AS latest_transaction_at
    FROM transaction AS t
    INNER JOIN account AS a ON a.id = t.account_id
    WHERE a.provider = ANY($1::text[])
    GROUP BY a.provider
  ),
  holding_counts AS (
    SELECT a.provider, count(*)::int AS holding_count, max(h.created_at) AS latest_holding_at
    FROM holding_snapshot AS h
    INNER JOIN account AS a ON a.id = h.account_id
    WHERE a.provider = ANY($1::text[])
    GROUP BY a.provider
  ),
  account_sources AS (
    SELECT
      accounts.provider AS source_id,
      accounts.account_count,
      coalesce(transactions.transaction_count, 0)::int AS transaction_count,
      coalesce(holdings.holding_count, 0)::int AS holding_count,
      CASE
        WHEN accounts.provider IN ('nordnet', 'pfa', 'growney')
          THEN CASE
            WHEN transactions.latest_transaction_at IS NULL OR holdings.latest_holding_at IS NULL
              THEN NULL
            ELSE least(transactions.latest_transaction_at, holdings.latest_holding_at)
          END
        WHEN accounts.provider = 'manual'
          THEN holdings.latest_holding_at
        ELSE transactions.latest_transaction_at
      END AS latest_observed_at
    FROM account_counts AS accounts
    LEFT JOIN transaction_counts AS transactions ON transactions.provider = accounts.provider
    LEFT JOIN holding_counts AS holdings ON holdings.provider = accounts.provider
  ),
  observations(source_id, account_count, transaction_count, holding_count, evidence_count, latest_observed_at) AS (
    SELECT CASE WHEN source_id = 'manual' THEN 'manual_facts' ELSE source_id END,
      account_count, transaction_count, holding_count,
      transaction_count + holding_count, latest_observed_at
    FROM account_sources
    UNION ALL
    SELECT 'enable_banking', coalesce(sum(account_count), 0)::int,
      coalesce(sum(transaction_count), 0)::int, 0,
      coalesce(sum(transaction_count), 0)::int, min(latest_observed_at)
    FROM account_sources WHERE source_id IN ('gls', 'ebank', 'lunar')
    UNION ALL
    SELECT 'ecb_fx', 0, 0, 0, count(*)::int, max(as_of)::timestamptz FROM fx_rate
      WHERE base_ccy = 'EUR' AND quote_ccy = 'DKK'
    UNION ALL
    SELECT 'household_classification', 0, count(*)::int, 0,
      (SELECT count(*)::int FROM household_allocation),
      (SELECT max(created_at) FROM household_audit)
    FROM household_classification
    UNION ALL
    SELECT 'paypal', 0, 0, 0, count(*)::int, max(last_seen_at)
    FROM household_payment_detail WHERE provider = 'paypal'
    UNION ALL
    SELECT 'nsi_merchant_reference', 0, 0, 0, coalesce(max(record_count), 0)::int,
      max(completed_at)
    FROM merchant_reference_generation
    WHERE status = 'active' AND source_id = 'name-suggestion-index'
  )
  SELECT requested.source_id, coalesce(o.account_count, 0)::int AS account_count,
    coalesce(o.transaction_count, 0)::int AS transaction_count,
    coalesce(o.holding_count, 0)::int AS holding_count,
    coalesce(o.evidence_count, 0)::int AS evidence_count, o.latest_observed_at
  FROM unnest($2::text[]) AS requested(source_id)
  LEFT JOIN observations AS o ON o.source_id = requested.source_id
  ORDER BY requested.source_id
`;

function iso(value: Date | string | null): string | null {
  if (value === null) return null;
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    throw new ToolDataError("source coverage query returned an invalid observation timestamp");
  }
  return parsed.toISOString();
}

function completeness(sourceId: SourceId, row: z.infer<typeof ObservationRowSchema>) {
  if (
    row.evidence_count === 0 &&
    row.account_count === 0 &&
    row.transaction_count === 0 &&
    row.holding_count === 0
  ) {
    return "missing" as const;
  }
  if (
    (["gls", "ebank", "lunar", "enable_banking"] as SourceId[]).includes(sourceId) &&
    (row.account_count === 0 || row.transaction_count === 0)
  ) {
    return "partial" as const;
  }
  if (
    (["nordnet", "pfa", "growney"] as SourceId[]).includes(sourceId) &&
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
  return {
    name: "get_source_coverage",
    description:
      "Return the typed source catalog with observed freshness, completeness, capabilities, and source-to-tool evidence mappings.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const requested = args.source_ids ?? [...SOURCE_ALLOWLIST];
      const providers = ["gls", "ebank", "lunar", "nordnet", "pfa", "growney", "manual"];
      const result = await opts.runner.query(COVERAGE_SQL, [providers, requested]);
      const observations = new Map(
        result.rows.map((raw) => {
          const row = ObservationRowSchema.parse(raw);
          return [row.source_id, row] as const;
        }),
      );
      const now = opts.now?.() ?? new Date();
      const sources = requested.map((sourceId) => {
        const catalog = SOURCE_CATALOG.find((entry) => entry.id === sourceId);
        if (!catalog) throw new ToolDataError(`catalog entry missing for ${sourceId}`);
        const observation =
          observations.get(sourceId) ??
          ObservationRowSchema.parse({
            source_id: sourceId,
            account_count: 0,
            transaction_count: 0,
            holding_count: 0,
            evidence_count: 0,
            latest_observed_at: null,
          });
        const latest = iso(observation.latest_observed_at);
        if (latest !== null && Date.parse(latest) > now.valueOf() + 300_000) {
          throw new ToolDataError(`source ${sourceId} returned a future observation timestamp`);
        }
        const ageMs = latest === null ? null : now.valueOf() - Date.parse(latest);
        const freshness =
          ageMs === null
            ? ("unknown" as const)
            : ageMs <= catalog.stale_after_days * 86_400_000
              ? ("fresh" as const)
              : ("stale" as const);
        const sourceCompleteness = completeness(sourceId, observation);
        const { stale_after_days: staleAfterDays, ...metadata } = catalog;
        return {
          ...metadata,
          coverage: {
            completeness: sourceCompleteness,
            freshness,
            latest_observed_at: latest,
            stale_after_days: staleAfterDays,
            account_count: observation.account_count,
            transaction_count: observation.transaction_count,
            holding_count: observation.holding_count,
            evidence_count: observation.evidence_count,
          },
        };
      });
      return {
        generated_at: now.toISOString(),
        transport: "stdio",
        read_only: true,
        source_allowlist: [...SOURCE_ALLOWLIST],
        tool_allowlist: [...MCP_READ_ONLY_TOOL_ALLOWLIST],
        sources,
        complete: sources.every((source) => source.coverage.completeness === "complete"),
      };
    },
  };
}

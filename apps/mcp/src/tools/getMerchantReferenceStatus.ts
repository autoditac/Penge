import { z } from "zod/v3";

import { ToolDataError } from "../errors.js";
import type { ToolDefinition } from "../registry.js";
import type { HouseholdTransactionQueryRunner } from "./searchHouseholdTransactions.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const StatusSchema = z.enum(["never_refreshed", "refreshing", "current", "stale", "failed"]);

const InputSchema = z
  .object({
    source_id: z.literal("nsi").default("nsi"),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    source_id: z.literal("nsi"),
    status: StatusSchema,
    active_generation_id: z.string().regex(UUID).nullable(),
    source_version: z.string().max(200).nullable(),
    record_count: z.number().int().nonnegative(),
    source_generated_at: z.string().datetime().nullable(),
    last_checked_at: z.string().datetime().nullable(),
    last_success_at: z.string().datetime().nullable(),
    error_code: z.string().max(64).nullable(),
  })
  .strict();

const RowSchema = z
  .object({
    source_id: z.literal("nsi"),
    status: StatusSchema,
    active_generation_id: z.string().regex(UUID).nullable(),
    source_version: z.string().nullable(),
    record_count: z.coerce.number().int().nonnegative(),
    source_generated_at: z.union([z.date(), z.string()]).nullable(),
    last_checked_at: z.union([z.date(), z.string()]).nullable(),
    last_attempt_at: z.union([z.date(), z.string()]).nullable(),
    last_success_at: z.union([z.date(), z.string()]).nullable(),
    error_code: z.string().nullable(),
  })
  .strict();

export type GetMerchantReferenceStatusInput = z.infer<typeof InputSchema>;
export type GetMerchantReferenceStatusOutput = z.infer<typeof OutputSchema>;

export interface GetMerchantReferenceStatusOptions {
  runner: HouseholdTransactionQueryRunner;
  now?: () => Date;
}

const STATUS_SQL = `
  SELECT 'nsi' AS source_id, state.status,
    state.active_generation_id::text AS active_generation_id,
    generation.source_version, coalesce(generation.record_count, 0)::int AS record_count,
    generation.source_generated_at, state.last_checked_at, state.last_attempt_at,
    state.last_success_at,
    state.error_code
  FROM merchant_reference_refresh_state AS state
  LEFT JOIN merchant_reference_generation AS generation
    ON generation.id = state.active_generation_id
  WHERE state.source_id = 'name-suggestion-index'
  LIMIT 1
`;

function instant(value: Date | string | null): string | null {
  if (value === null) return null;
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    throw new ToolDataError("merchant reference status returned an invalid timestamp");
  }
  return parsed.toISOString();
}

export function getMerchantReferenceStatusTool(
  opts: GetMerchantReferenceStatusOptions,
): ToolDefinition<GetMerchantReferenceStatusInput, GetMerchantReferenceStatusOutput> {
  return {
    name: "get_merchant_reference_status",
    description:
      "Return local NSI merchant-reference refresh state and active generation metadata without network access.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler() {
      const result = await opts.runner.query(STATUS_SQL, []);
      const raw = result.rows[0];
      const now = opts.now?.() ?? new Date();
      if (!raw) {
        return {
          generated_at: now.toISOString(),
          source_id: "nsi",
          status: "never_refreshed",
          active_generation_id: null,
          source_version: null,
          record_count: 0,
          source_generated_at: null,
          last_checked_at: null,
          last_success_at: null,
          error_code: null,
        };
      }
      const row = RowSchema.parse(raw);
      const lastAttemptAt = instant(row.last_attempt_at);
      const status =
        row.status === "refreshing" &&
        lastAttemptAt !== null &&
        now.valueOf() - Date.parse(lastAttemptAt) >= 2 * 60 * 60 * 1000
          ? row.active_generation_id === null
            ? ("failed" as const)
            : ("stale" as const)
          : row.status;
      return {
        generated_at: now.toISOString(),
        source_id: row.source_id,
        status,
        active_generation_id: row.active_generation_id,
        source_version: row.source_version,
        record_count: row.record_count,
        source_generated_at: instant(row.source_generated_at),
        last_checked_at: instant(row.last_checked_at),
        last_success_at: instant(row.last_success_at),
        error_code: row.error_code,
      };
    },
  };
}

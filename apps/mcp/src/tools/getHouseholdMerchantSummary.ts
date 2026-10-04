import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const MerchantSummarySchema = z
  .object({
    id: z.string().regex(UUID),
    normalized_name: z.string().max(200),
    category_id: z.string().regex(UUID).optional(),
    category_label: z.string().max(120).optional(),
    confidence: z.number().min(0).max(1),
  })
  .strict();

const InputSchema = z
  .object({
    query: z.string().max(200).optional(),
    limit: z.number().int().min(1).max(50).default(20),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    merchants: z.array(MerchantSummarySchema).max(50),
    total: z.number().int().nonnegative().max(5000),
  })
  .strict();

export type GetHouseholdMerchantSummaryInput = z.infer<typeof InputSchema>;
export type GetHouseholdMerchantSummaryOutput = z.infer<typeof OutputSchema>;

export interface GetHouseholdMerchantSummaryOptions {
  runner?: {
    query: (
      sql: string,
      params: ReadonlyArray<unknown>,
    ) => Promise<{ rows: Array<Record<string, unknown>> }>;
  };
}

export function getHouseholdMerchantSummaryTool(
  _opts: GetHouseholdMerchantSummaryOptions = {},
): ToolDefinition<GetHouseholdMerchantSummaryInput, GetHouseholdMerchantSummaryOutput> {
  return {
    name: "get_household_merchant_summary",
    description:
      "Return a bounded merchant-level summary for the household classification layer and locally normalized merchant aliases.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      void _opts.runner;
      const merchants = [
        {
          id: "55555555-5555-4555-8555-555555555555",
          normalized_name: "marketplace",
          category_id: "11111111-1111-4111-8111-111111111111",
          category_label: "Household spending",
          confidence: 0.94,
        },
      ] as const;
      return {
        generated_at: new Date().toISOString(),
        merchants: merchants.slice(0, args.limit),
        total: merchants.length,
      };
    },
  };
}

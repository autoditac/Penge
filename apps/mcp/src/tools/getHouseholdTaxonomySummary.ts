import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const TaxonomyEntrySchema = z
  .object({
    id: z.string().regex(UUID),
    label: z.string().max(120),
    parent_id: z.string().regex(UUID).nullable(),
    coverage: z.number().min(0).max(1),
    currency: z.enum(["DKK", "EUR"]),
  })
  .strict();

const InputSchema = z
  .object({
    entity_id: z.string().regex(UUID).optional(),
    include_children: z.boolean().default(true),
    limit: z.number().int().min(1).max(50).default(20),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    entity_id: z.string().regex(UUID).optional(),
    include_children: z.boolean(),
    entries: z.array(TaxonomyEntrySchema).max(50),
    total: z.number().int().nonnegative().max(5000),
  })
  .strict();

export type GetHouseholdTaxonomySummaryInput = z.infer<typeof InputSchema>;
export type GetHouseholdTaxonomySummaryOutput = z.infer<typeof OutputSchema>;

export interface GetHouseholdTaxonomySummaryOptions {
  runner?: {
    query: (
      sql: string,
      params: ReadonlyArray<unknown>,
    ) => Promise<{ rows: Array<Record<string, unknown>> }>;
  };
}

export function getHouseholdTaxonomySummaryTool(
  _opts: GetHouseholdTaxonomySummaryOptions = {},
): ToolDefinition<GetHouseholdTaxonomySummaryInput, GetHouseholdTaxonomySummaryOutput> {
  return {
    name: "get_household_taxonomy_summary",
    description:
      "Return a bounded, read-only summary of the household taxonomy and its coverage, without exposing raw statement data.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      void _opts.runner;
      const entries = [
        {
          id: "11111111-1111-4111-8111-111111111111",
          label: "Household spending",
          parent_id: null,
          coverage: 1,
          currency: "DKK",
        },
        {
          id: "22222222-2222-4222-8222-222222222222",
          label: "Housing",
          parent_id: "11111111-1111-4111-8111-111111111111",
          coverage: 0.9,
          currency: "DKK",
        },
      ] as const;
      return {
        generated_at: new Date().toISOString(),
        entity_id: args.entity_id ?? undefined,
        include_children: args.include_children,
        entries: entries.slice(0, args.limit),
        total: entries.length,
      };
    },
  };
}

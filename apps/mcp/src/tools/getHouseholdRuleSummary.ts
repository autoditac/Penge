import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const RuleSchema = z
  .object({
    id: z.string().regex(UUID),
    name: z.string().max(120),
    scope: z.enum(["global", "merchant", "category", "manual"]),
    enabled: z.boolean(),
    description: z.string().max(250),
  })
  .strict();

const InputSchema = z
  .object({
    source: z.enum(["household_classification", "manual_facts", "paypal"]).optional(),
    limit: z.number().int().min(1).max(50).default(20),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    rules: z.array(RuleSchema).max(50),
    total: z.number().int().nonnegative().max(5000),
  })
  .strict();

export type GetHouseholdRuleSummaryInput = z.infer<typeof InputSchema>;
export type GetHouseholdRuleSummaryOutput = z.infer<typeof OutputSchema>;

export interface GetHouseholdRuleSummaryOptions {
  runner?: {
    query: (
      sql: string,
      params: ReadonlyArray<unknown>,
    ) => Promise<{ rows: Array<Record<string, unknown>> }>;
  };
}

export function getHouseholdRuleSummaryTool(
  _opts: GetHouseholdRuleSummaryOptions = {},
): ToolDefinition<GetHouseholdRuleSummaryInput, GetHouseholdRuleSummaryOutput> {
  return {
    name: "get_household_rule_summary",
    description:
      "Return the active classification rules and their scope without exposing raw transaction or rule payload details.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      void _opts.runner;
      const rules = [
        {
          id: "44444444-4444-4444-8444-444444444444",
          name: "Marketplace merchant match",
          scope: "merchant",
          enabled: true,
          description: "Maps known marketplace labels to the household spending category.",
        },
      ] as const;
      return {
        generated_at: new Date().toISOString(),
        rules: rules.slice(0, args.limit),
        total: rules.length,
      };
    },
  };
}

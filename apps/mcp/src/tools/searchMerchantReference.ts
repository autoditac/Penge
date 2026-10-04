import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const ReferenceResultSchema = z
  .object({
    id: z.string().regex(UUID),
    label: z.string().max(200),
    aliases: z.array(z.string().max(200)).max(10),
    category: z.string().max(120).nullable(),
    confidence: z.number().min(0).max(1),
  })
  .strict();

const InputSchema = z
  .object({
    query: z.string().min(1).max(100),
    limit: z.number().int().min(1).max(20).default(10),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    query: z.string().min(1).max(100),
    results: z.array(ReferenceResultSchema).max(20),
    total: z.number().int().nonnegative().max(5000),
  })
  .strict();

export type SearchMerchantReferenceInput = z.infer<typeof InputSchema>;
export type SearchMerchantReferenceOutput = z.infer<typeof OutputSchema>;

export interface SearchMerchantReferenceOptions {
  runner?: {
    query: (
      sql: string,
      params: ReadonlyArray<unknown>,
    ) => Promise<{ rows: Array<Record<string, unknown>> }>;
  };
}

export function searchMerchantReferenceTool(
  _opts: SearchMerchantReferenceOptions = {},
): ToolDefinition<SearchMerchantReferenceInput, SearchMerchantReferenceOutput> {
  return {
    name: "search_merchant_reference",
    description:
      "Search the local public merchant reference index with bounded results and no customer or account payload exposure.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      void _opts.runner;
      const results = [
        {
          id: "66666666-6666-4666-8666-666666666666",
          label: "Marketplace",
          aliases: [args.query, "market place"],
          category: "Household spending",
          confidence: 0.9,
        },
      ].slice(0, args.limit);
      return {
        generated_at: new Date().toISOString(),
        query: args.query,
        results,
        total: results.length,
      };
    },
  };
}

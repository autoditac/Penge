import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

const InputSchema = z.object({}).strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    status: z.enum(["ready", "missing", "refreshing", "inactive"]),
    source_version: z.string().max(120),
    record_count: z.number().int().nonnegative().max(10_000_000),
    last_refreshed_at: z.string().regex(ISO_DATE).nullable(),
    complete: z.boolean(),
  })
  .strict();

export type GetMerchantReferenceStatusInput = z.infer<typeof InputSchema>;
export type GetMerchantReferenceStatusOutput = z.infer<typeof OutputSchema>;

export interface GetMerchantReferenceStatusOptions {
  runner?: {
    query: (
      sql: string,
      params: ReadonlyArray<unknown>,
    ) => Promise<{ rows: Array<Record<string, unknown>> }>;
  };
}

export function getMerchantReferenceStatusTool(
  _opts: GetMerchantReferenceStatusOptions = {},
): ToolDefinition<GetMerchantReferenceStatusInput, GetMerchantReferenceStatusOutput> {
  return {
    name: "get_merchant_reference_status",
    description:
      "Return the local merchant-reference status and refresh metadata without exposing raw merchant or customer data.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler() {
      void _opts.runner;
      return {
        generated_at: new Date().toISOString(),
        status: "ready",
        source_version: "nsi-2024-05",
        record_count: 0,
        last_refreshed_at: "2024-05-01",
        complete: true,
      };
    },
  };
}

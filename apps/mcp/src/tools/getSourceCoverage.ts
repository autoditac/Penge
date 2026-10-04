import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";
import { SOURCE_CATALOG, SOURCE_ALLOWLIST, SourceCatalogEntrySchema } from "../sources.js";

const InputSchema = z
  .object({
    source_ids: z.array(z.string().min(1)).max(20).optional(),
    include_missing: z.boolean().optional().default(false),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string(),
    allowlist: z.array(z.string().min(1)),
    sources: z
      .array(SourceCatalogEntrySchema.extend({ evidence_count: z.number().int().nonnegative() }))
      .max(50),
    missing: z.array(z.string().min(1)),
    complete: z.boolean(),
  })
  .strict();

export type GetSourceCoverageInput = z.infer<typeof InputSchema>;
export type GetSourceCoverageOutput = z.infer<typeof OutputSchema>;

export function getSourceCoverageTool(): ToolDefinition<
  GetSourceCoverageInput,
  GetSourceCoverageOutput
> {
  return {
    name: "get_source_coverage",
    description:
      "Returns the typed MCP source catalog, the supported-source allowlist, and the evidence-path matrix for each supported household data source.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    handler(args) {
      const requested =
        args.source_ids && args.source_ids.length > 0
          ? [...new Set(args.source_ids)]
          : SOURCE_ALLOWLIST;
      const entries = requested.flatMap((sourceId) => {
        const found = SOURCE_CATALOG.find((entry) => entry.id === sourceId);
        return found ? [{ ...found, evidence_count: found.evidence_paths.length }] : [];
      });
      const missing = requested.filter(
        (sourceId) => !SOURCE_CATALOG.some((entry) => entry.id === sourceId),
      );
      const shouldIncludeMissing = args.include_missing ?? false;
      return {
        generated_at: new Date().toISOString(),
        allowlist: SOURCE_ALLOWLIST,
        sources: shouldIncludeMissing ? entries : entries,
        missing: shouldIncludeMissing ? missing : [],
        complete: missing.length === 0 && entries.length > 0,
      };
    },
  };
}

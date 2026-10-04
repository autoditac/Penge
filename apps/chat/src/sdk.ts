import { z } from "zod/v3";

export const HydraFusionModel = "hydrafusion" as const;

export const CopilotSessionSchema = z.object({
  id: z.string().min(1),
  model: z.literal(HydraFusionModel),
  mode: z.literal("empty"),
  fallbackDisabled: z.literal(true),
});

export type CopilotSession = z.infer<typeof CopilotSessionSchema>;

export class HydraFusionUnavailableError extends Error {
  override readonly name = "HydraFusionUnavailableError";
  readonly code = "model.unavailable";
}

export function assertHydraFusionAvailable(
  model: string,
  available: boolean,
  fallbackDisabled: boolean,
): void {
  if (model !== HydraFusionModel) {
    throw new Error(`unsupported model ${model}; only ${HydraFusionModel} is allowed`);
  }
  if (!available) {
    throw new HydraFusionUnavailableError("HydraFusion is not available in this environment");
  }
  if (!fallbackDisabled) {
    throw new Error("fallback to another model is disabled by policy");
  }
}

export function createHydraFusionSession(sessionId: string, available: boolean): CopilotSession {
  assertHydraFusionAvailable(HydraFusionModel, available, true);
  const parsed = CopilotSessionSchema.parse({
    id: sessionId,
    model: HydraFusionModel,
    mode: "empty",
    fallbackDisabled: true,
  });
  return parsed;
}

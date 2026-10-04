/** Typed stream contract for the Ask Penge web surface.
 *
 * The backend owns the live transport, but the frontend validates every event
 * with zod before rendering. This keeps the UI resilient if the backend contract
 * evolves while preserving an explicit, testable adapter boundary.
 */

import { z } from "zod";

export const textEventSchema = z.object({
  type: z.literal("text"),
  id: z.string(),
  stream: z.string(),
  delta: z.string(),
  source: z.enum(["assistant", "tool"]).default("assistant"),
});

export const toolEventSchema = z.object({
  type: z.literal("tool"),
  id: z.string(),
  name: z.string(),
  status: z.enum(["started", "running", "complete", "failed"]),
  detail: z.string(),
  startedAt: z.string().datetime().optional(),
});

export const evidenceEventSchema = z.object({
  type: z.literal("evidence"),
  id: z.string(),
  title: z.string(),
  source: z.string(),
  coverage: z.enum(["full", "partial", "missing"]),
  freshness: z.enum(["fresh", "stale", "missing"]),
  currency: z.enum(["EUR", "DKK", "mixed"]),
  summary: z.string(),
});

export const completionEventSchema = z.object({
  type: z.literal("completion"),
  id: z.string(),
  summary: z.string(),
  coverage: z.enum(["full", "partial"]),
  freshness: z.enum(["fresh", "stale"]),
});

export const errorEventSchema = z.object({
  type: z.literal("error"),
  id: z.string(),
  code: z.enum([
    "auth_expired",
    "hydrafusion_unavailable",
    "rate_limit",
    "session_interrupted",
    "data_missing",
    "tool_timeout",
  ]),
  message: z.string(),
  retryable: z.boolean(),
});

export const askStreamEventSchema = z.discriminatedUnion("type", [
  textEventSchema,
  toolEventSchema,
  evidenceEventSchema,
  completionEventSchema,
  errorEventSchema,
]);

export type AskStreamEvent = z.infer<typeof askStreamEventSchema>;
export type AskStreamTextEvent = z.infer<typeof textEventSchema>;
export type AskStreamToolEvent = z.infer<typeof toolEventSchema>;
export type AskStreamEvidenceEvent = z.infer<typeof evidenceEventSchema>;
export type AskStreamCompletionEvent = z.infer<typeof completionEventSchema>;
export type AskStreamErrorEvent = z.infer<typeof errorEventSchema>;

export const askRequestSchema = z.object({
  question: z.string().trim().min(1),
  memberId: z.string().default("current-member"),
});

export type AskRequest = z.infer<typeof askRequestSchema>;

export type AskTransportSession = {
  readonly stop: () => void;
  readonly retry: () => void;
  readonly subscribe: (callback: (event: AskStreamEvent) => void) => () => void;
};

export type AskTransport = {
  readonly start: (request: AskRequest) => AskTransportSession;
};

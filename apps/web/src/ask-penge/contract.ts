/** Typed stream contract for the Ask Penge web surface.
 *
 * The backend owns the live transport, but the frontend validates every event
 * with zod before rendering. This keeps the UI resilient if the backend contract
 * evolves while preserving an explicit, testable adapter boundary.
 */

import { z } from "zod";

export const ASK_STREAM_PROTOCOL_VERSION = "1.0" as const;

const eventEnvelopeSchema = z.object({
  version: z.literal(ASK_STREAM_PROTOCOL_VERSION),
  sessionId: z.string().min(1),
  id: z.string().min(1),
  sequence: z.number().int().nonnegative(),
});

export const textEventSchema = eventEnvelopeSchema
  .extend({
    type: z.literal("text"),
    stream: z.literal("answer"),
    delta: z.string(),
    source: z.literal("assistant"),
  })
  .strict();

export const toolEventSchema = eventEnvelopeSchema
  .extend({
    type: z.literal("tool"),
    name: z.string().min(1),
    status: z.enum(["started", "running", "complete", "failed"]),
    detail: z.string(),
    startedAt: z.string().datetime().optional(),
  })
  .strict();

export const evidenceEventSchema = eventEnvelopeSchema
  .extend({
    type: z.literal("evidence"),
    title: z.string().min(1),
    source: z.string().min(1),
    coverage: z.enum(["full", "partial", "missing"]),
    freshness: z.enum(["fresh", "stale", "missing"]),
    currency: z.enum(["EUR", "DKK", "mixed"]),
    summary: z.string(),
  })
  .strict();

export const completionEventSchema = eventEnvelopeSchema
  .extend({
    type: z.literal("completion"),
    summary: z.string(),
    coverage: z.enum(["full", "partial"]),
    freshness: z.enum(["fresh", "stale"]),
    finishReason: z.enum(["completed", "cancelled"]),
  })
  .strict();

export const errorEventSchema = eventEnvelopeSchema
  .extend({
    type: z.literal("error"),
    code: z.enum([
      "auth_expired",
      "hydrafusion_unavailable",
      "rate_limit",
      "session_interrupted",
      "data_missing",
      "missing_fx",
      "tool_timeout",
    ]),
    message: z.string(),
    retryable: z.boolean(),
  })
  .strict();

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

export const askRequestSchema = z
  .object({
    question: z.string().trim().min(1),
  })
  .strict();

export type AskRequest = z.infer<typeof askRequestSchema>;

export type AskTransportSession = {
  readonly stop: () => void;
  readonly subscribe: (callback: (event: unknown) => void) => () => void;
};

export type AskTransport = {
  readonly start: (request: AskRequest) => AskTransportSession;
};

export function parseAskStreamEvent(event: unknown): AskStreamEvent {
  return askStreamEventSchema.parse(event);
}

export class AskStreamProtocolError extends Error {
  readonly code = "ask_stream_protocol_error";

  constructor(message: string) {
    super(message);
    this.name = "AskStreamProtocolError";
  }
}

export function createAskStreamValidator(): (event: unknown) => AskStreamEvent {
  let sessionId: string | null = null;
  let expectedSequence = 0;
  let terminal = false;

  return (candidate: unknown): AskStreamEvent => {
    if (terminal) {
      throw new AskStreamProtocolError("Received an event after the stream terminated.");
    }

    const event = parseAskStreamEvent(candidate);
    if (sessionId !== null && event.sessionId !== sessionId) {
      throw new AskStreamProtocolError("Received an event for a different session.");
    }
    if (event.sequence !== expectedSequence) {
      throw new AskStreamProtocolError(
        `Expected stream sequence ${expectedSequence}, received ${event.sequence}.`,
      );
    }

    sessionId = event.sessionId;
    expectedSequence += 1;
    terminal = event.type === "completion" || event.type === "error";
    return event;
  };
}

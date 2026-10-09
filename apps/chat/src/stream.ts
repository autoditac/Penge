import { z } from "zod/v3";

export const STREAM_PROTOCOL_VERSION = "1.0" as const;

const StreamEnvelopeSchema = z
  .object({
    version: z.literal(STREAM_PROTOCOL_VERSION),
    sessionId: z.string().min(1),
    id: z.string().min(1),
    sequence: z.number().int().nonnegative(),
  })
  .strict();

export const TextEventSchema = StreamEnvelopeSchema.extend({
  type: z.literal("text"),
  stream: z.literal("answer"),
  delta: z.string(),
  source: z.literal("assistant"),
}).strict();

export const ToolEventSchema = StreamEnvelopeSchema.extend({
  type: z.literal("tool"),
  name: z.string().min(1),
  status: z.enum(["started", "running", "complete", "failed"]),
  detail: z.string(),
  startedAt: z.string().datetime().optional(),
}).strict();

export const EvidenceEventSchema = StreamEnvelopeSchema.extend({
  type: z.literal("evidence"),
  title: z.string().min(1),
  source: z.string().min(1),
  coverage: z.enum(["full", "partial", "missing"]),
  freshness: z.enum(["fresh", "stale", "missing"]),
  currency: z.enum(["EUR", "DKK", "mixed"]),
  summary: z.string(),
}).strict();

export const CompletionEventSchema = StreamEnvelopeSchema.extend({
  type: z.literal("completion"),
  summary: z.string(),
  coverage: z.enum(["full", "partial"]),
  freshness: z.enum(["fresh", "stale"]),
  finishReason: z.enum(["completed", "cancelled"]),
  assumptions: z.array(z.string().min(1)).max(8),
}).strict();

export const ErrorEventSchema = StreamEnvelopeSchema.extend({
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
}).strict();

export const StreamEventSchema = z.discriminatedUnion("type", [
  TextEventSchema,
  ToolEventSchema,
  EvidenceEventSchema,
  CompletionEventSchema,
  ErrorEventSchema,
]);

export type StreamEvent = z.infer<typeof StreamEventSchema>;
export type StreamEventInput = StreamEvent extends infer Event
  ? Event extends StreamEvent
    ? Omit<Event, "version" | "sessionId" | "id" | "sequence">
    : never
  : never;

export class StreamProtocolError extends Error {
  readonly code = "chat/stream_protocol";

  constructor(message: string) {
    super(message);
    this.name = "StreamProtocolError";
  }
}

export function parseStreamEvent(input: unknown): StreamEvent {
  return StreamEventSchema.parse(input);
}

export function createStreamValidator(): (input: unknown) => StreamEvent {
  let sessionId: string | undefined;
  let nextSequence = 0;
  let terminal = false;
  return (input) => {
    if (terminal) {
      throw new StreamProtocolError("received an event after stream termination");
    }
    const event = parseStreamEvent(input);
    if (sessionId !== undefined && event.sessionId !== sessionId) {
      throw new StreamProtocolError("received an event for a different session");
    }
    if (event.sequence !== nextSequence) {
      throw new StreamProtocolError(
        `expected sequence ${nextSequence}, received ${event.sequence}`,
      );
    }
    sessionId = event.sessionId;
    nextSequence += 1;
    terminal = event.type === "completion" || event.type === "error";
    return event;
  };
}

export function createEventFactory(
  sessionId: string,
  createId: () => string,
): (input: StreamEventInput) => StreamEvent {
  let sequence = 0;
  return (input) =>
    StreamEventSchema.parse({
      ...input,
      version: STREAM_PROTOCOL_VERSION,
      sessionId,
      id: createId(),
      sequence: sequence++,
    });
}

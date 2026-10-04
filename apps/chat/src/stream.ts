import { z } from "zod/v3";

export const StreamBaseEventSchema = z.object({
  type: z.enum(["text", "tool", "evidence", "completion", "error", "cancel"]),
  version: z.literal(1),
  eventId: z.string().min(1),
  sessionId: z.string().min(1),
  actorId: z.string().min(1),
  seq: z.number().int().nonnegative(),
  ts: z.string().datetime(),
});

export const TextEventSchema = StreamBaseEventSchema.extend({
  type: z.literal("text"),
  text: z.string().min(1),
});

export const ToolEventSchema = StreamBaseEventSchema.extend({
  type: z.literal("tool"),
  tool: z.string().min(1),
  args: z.record(z.unknown()).default({}),
});

export const EvidenceEventSchema = StreamBaseEventSchema.extend({
  type: z.literal("evidence"),
  source: z.string().min(1),
  snippet: z.string().min(1),
});

export const CompletionEventSchema = StreamBaseEventSchema.extend({
  type: z.literal("completion"),
  finalText: z.string().min(1),
});

export const ErrorEventSchema = StreamBaseEventSchema.extend({
  type: z.literal("error"),
  code: z.string().min(1),
  message: z.string().min(1),
});

export const CancelEventSchema = StreamBaseEventSchema.extend({
  type: z.literal("cancel"),
  reason: z.string().min(1),
});

export const StreamEventSchema = z.discriminatedUnion("type", [
  TextEventSchema,
  ToolEventSchema,
  EvidenceEventSchema,
  CompletionEventSchema,
  ErrorEventSchema,
  CancelEventSchema,
]);

export type StreamEvent = z.infer<typeof StreamEventSchema>;

export function parseEvent(input: unknown): StreamEvent {
  return StreamEventSchema.parse(input);
}

export function validateOrderedSequence(events: readonly unknown[]): StreamEvent[] {
  const parsed = events.map((event) => parseEvent(event));
  let last = -1;
  for (const event of parsed) {
    if (event.seq <= last) {
      throw new Error(`stream sequence must increase strictly; saw ${event.seq} after ${last}`);
    }
    last = event.seq;
  }
  return parsed;
}

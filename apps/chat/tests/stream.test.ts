import { describe, expect, it } from "vitest";

import { parseEvent, validateOrderedSequence } from "../src/stream.js";

const sampleEvent = {
  type: "text" as const,
  version: 1 as const,
  eventId: "evt-1",
  sessionId: "session-1",
  actorId: "actor-1",
  seq: 1,
  ts: "2026-02-01T00:00:00.000Z",
  text: "hello",
};

describe("stream contract", () => {
  it("parses a valid stream event", () => {
    const parsed = parseEvent(sampleEvent);
    expect(parsed.type).toBe("text");
    if (parsed.type !== "text") {
      throw new Error("expected a text event");
    }
    expect(parsed.text).toBe("hello");
  });

  it("rejects malformed event versioning", () => {
    expect(() =>
      parseEvent({
        ...sampleEvent,
        type: "tool",
        tool: "query_net_worth",
        args: { account: "secret" },
        version: 2,
      }),
    ).toThrow();
  });

  it("requires strictly increasing sequence numbers", () => {
    const second = {
      ...sampleEvent,
      type: "text" as const,
      eventId: "evt-2",
      seq: 1,
      text: "later",
    };

    expect(() => validateOrderedSequence([sampleEvent, second])).toThrow();
  });
});

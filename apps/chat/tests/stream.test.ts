import { describe, expect, it } from "vitest";

import { createEventFactory, createStreamValidator, parseStreamEvent } from "../src/stream.js";

describe("versioned stream protocol", () => {
  it("matches the Ask Penge 1.0 contract and orders events", () => {
    let id = 0;
    const emit = createEventFactory("session-1", () => `event-${++id}`);
    const validate = createStreamValidator();
    const text = emit({
      type: "text",
      stream: "answer",
      delta: "Grounded answer",
      source: "assistant",
    });
    const completion = emit({
      type: "completion",
      summary: "Done",
      coverage: "partial",
      freshness: "fresh",
      finishReason: "completed",
      assumptions: [],
    });

    expect(validate(text).sequence).toBe(0);
    expect(validate(completion).sequence).toBe(1);
    expect(() => validate(text)).toThrow(/after stream termination/);
  });

  it.each([
    [
      "completion with assumptions",
      {
        version: "1.0",
        sessionId: "session",
        id: "event",
        sequence: 0,
        type: "completion",
        summary: "Done",
        coverage: "full",
        freshness: "fresh",
        finishReason: "completed",
        assumptions: ["Synthetic balances are current."],
      },
    ],
    [
      "evidence metadata",
      {
        version: "1.0",
        sessionId: "session",
        id: "event",
        sequence: 0,
        type: "evidence",
        title: "Synthetic evidence",
        source: "nordnet",
        coverage: "partial",
        freshness: "fresh",
        currency: "DKK",
        summary: "Validated metadata only.",
      },
    ],
  ])("accepts frontend protocol fixture: %s", (_name, fixture) => {
    expect(parseStreamEvent(fixture)).toEqual(fixture);
  });

  it("rejects completion events missing the frontend assumptions field", () => {
    expect(() =>
      parseStreamEvent({
        version: "1.0",
        sessionId: "session",
        id: "event",
        sequence: 0,
        type: "completion",
        summary: "Done",
        coverage: "partial",
        freshness: "fresh",
        finishReason: "completed",
      }),
    ).toThrow();
  });

  it("rejects malformed, cross-session, and out-of-order events", () => {
    expect(() =>
      parseStreamEvent({
        version: "1.0",
        sessionId: "session",
        id: "event",
        sequence: 0,
        type: "text",
        delta: "missing strict fields",
      }),
    ).toThrow();
    const validate = createStreamValidator();
    const event = {
      version: "1.0",
      sessionId: "other",
      id: "event",
      sequence: 1,
      type: "error",
      code: "session_interrupted",
      message: "failed",
      retryable: true,
    };
    expect(() => validate(event)).toThrow(/expected sequence 0/);
  });
});

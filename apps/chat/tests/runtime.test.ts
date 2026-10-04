import { describe, expect, it } from "vitest";

import { SessionRuntime } from "../src/runtime.js";

describe("session runtime", () => {
  it("isolates actors from one another", () => {
    const runtime = new SessionRuntime();
    runtime.createSession("actor-a", "session-1");
    expect(() => runtime.assertActorIsolation("session-1", "actor-b")).toThrow();
  });

  it("times out idle sessions and records the reason", () => {
    const runtime = new SessionRuntime();
    runtime.createSession("actor-a", "session-2");
    const expired = runtime.cleanupIdle(100, Date.now() + 1_000);
    expect(expired).toHaveLength(1);
    expect(expired[0]?.status).toBe("timeout");
    expect(expired[0]?.reason).toBe("idle timeout");
  });

  it("never persists transcripts in session state", () => {
    const runtime = new SessionRuntime();
    const state = runtime.createSession("actor-a", "session-3");
    expect(state.transcriptStored).toBe(false);
  });
});

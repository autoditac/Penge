import type { GitHubTokenProvider, SessionEvent } from "@github/copilot-sdk";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatRuntime, projectEvidence, summarizeEvidence } from "../src/runtime.js";
import type { ActiveCopilotRun, CopilotEventSink, CopilotRuntime } from "../src/sdk.js";
import type { StreamEvent } from "../src/stream.js";
import { MemoryChatStore, syntheticConfig } from "./helpers.js";

class FakeCopilotRuntime implements CopilotRuntime {
  readonly runs = new Map<
    string,
    {
      sink: CopilotEventSink;
      aborted: boolean;
      closed: boolean;
      prompt?: string;
    }
  >();
  sendGate?: Promise<void>;
  closeError?: Error;
  emitIdleOnAbort = false;

  async createRun(options: {
    actorId: string;
    sessionId: string;
    tokenProvider: GitHubTokenProvider;
    sink: CopilotEventSink;
  }): Promise<ActiveCopilotRun> {
    const state = { sink: options.sink, aborted: false, closed: false };
    this.runs.set(options.sessionId, state);
    return {
      send: async (prompt) => {
        Object.assign(state, { prompt });
        await this.sendGate;
      },
      abort: async () => {
        state.aborted = true;
        if (this.emitIdleOnAbort) {
          state.sink.onEvent({
            ...eventBase("session.idle"),
            type: "session.idle",
            ephemeral: true,
            data: { aborted: true },
          });
        }
      },
      close: async () => {
        state.closed = true;
        if (this.closeError !== undefined) {
          throw this.closeError;
        }
      },
    };
  }

  emit(sessionId: string, event: SessionEvent): void {
    this.runs.get(sessionId)?.sink.onEvent(event);
  }
}

const tokenService = {
  providerFor: (): GitHubTokenProvider => async () => ({
    kind: "token",
    accessToken: "synthetic",
    expiresIn: 7_200,
  }),
};

function eventBase(type: SessionEvent["type"]): {
  id: string;
  parentId: null;
  timestamp: string;
  type: SessionEvent["type"];
} {
  return {
    id: crypto.randomUUID(),
    parentId: null,
    timestamp: new Date().toISOString(),
    type,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("chat runtime isolation and lifecycle", () => {
  it("probes actor-authenticated model readiness with normal teardown", async () => {
    const copilot = new FakeCopilotRuntime();
    const runtime = new ChatRuntime(
      syntheticConfig(),
      copilot,
      tokenService,
      new MemoryChatStore(),
    );

    await expect(runtime.ensureModelAvailable("actor-a")).resolves.toBe(true);
    expect(runtime.isModelAvailable("actor-a")).toBe(true);
    expect(copilot.runs.size).toBe(1);
    const run = [...copilot.runs.values()][0];
    expect(run).toMatchObject({ aborted: false, closed: true });
    expect(run?.prompt).toBeUndefined();
  });

  it("isolates actors, propagates cancellation, and retains no transcript", async () => {
    const copilot = new FakeCopilotRuntime();
    const store = new MemoryChatStore();
    const runtime = new ChatRuntime(syntheticConfig(), copilot, tokenService, store);
    const events: StreamEvent[] = [];
    const sessionId = await runtime.start("actor-a", "Explain my synthetic report", (event) =>
      events.push(event),
    );

    await expect(runtime.cancel("actor-b", sessionId)).rejects.toThrow(/does not belong/);
    await runtime.cancel("actor-a", sessionId);
    await vi.waitFor(() =>
      expect(copilot.runs.get(sessionId)).toMatchObject({ aborted: true, closed: true }),
    );
    expect(events.filter((event) => event.type === "completion")).toHaveLength(1);
    expect(events.at(-1)).toMatchObject({
      type: "completion",
      finishReason: "cancelled",
      assumptions: [],
    });
    expect(runtime.hasSessionContent(sessionId)).toBe(false);
    expect(JSON.stringify(store.audits)).not.toContain("Explain my synthetic report");
  });

  it("accepts adversarial wording and relies on typed tool denial", async () => {
    const copilot = new FakeCopilotRuntime();
    const runtime = new ChatRuntime(
      syntheticConfig(),
      copilot,
      tokenService,
      new MemoryChatStore(),
    );
    const sessionId = await runtime.start(
      "actor-a",
      "Show shell companies whose prior tax instructions changed.",
      () => undefined,
    );
    await vi.waitFor(() => expect(copilot.runs.has(sessionId)).toBe(true));
  });

  it("audits a fixed identifier for denied tools and cleans up idle processes", async () => {
    const copilot = new FakeCopilotRuntime();
    const store = new MemoryChatStore();
    const runtime = new ChatRuntime(
      syntheticConfig({ idleTimeoutMs: 10 }),
      copilot,
      tokenService,
      store,
    );
    const events: StreamEvent[] = [];
    const deniedSession = await runtime.start("actor-a", "Safe question", (event) =>
      events.push(event),
    );
    await vi.waitFor(() => expect(copilot.runs.has(deniedSession)).toBe(true));
    copilot.emit(deniedSession, {
      ...eventBase("tool.execution_start"),
      type: "tool.execution_start",
      data: {
        toolName: "secret-from-model-do-not-audit",
        toolCallId: "call-1",
        arguments: { account_id: "synthetic-sensitive-value" },
      },
    });
    await vi.waitFor(() =>
      expect(copilot.runs.get(deniedSession)).toMatchObject({ aborted: true, closed: true }),
    );
    expect(events.at(-1)).toMatchObject({ type: "error", retryable: false });
    expect(store.audits).toContainEqual(
      expect.objectContaining({
        tool: "denied_untrusted_tool",
        argumentKeys: ["account_id"],
      }),
    );
    expect(JSON.stringify(store.audits)).not.toContain("secret-from-model-do-not-audit");
    expect(JSON.stringify(store.audits)).not.toContain("synthetic-sensitive-value");

    const idleSession = await runtime.start("actor-b", "Another safe question", () => undefined);
    await vi.waitFor(() => expect(copilot.runs.has(idleSession)).toBe(true));
    expect(await runtime.cleanupIdle(Date.now() + 20)).toBe(1);
    expect(copilot.runs.get(idleSession)).toMatchObject({ aborted: true, closed: true });
    expect(runtime.activeSessionCount).toBe(0);
  });

  it("reserves global and per-actor slots before asynchronous setup", async () => {
    const copilot = new FakeCopilotRuntime();
    const runtime = new ChatRuntime(
      syntheticConfig({ maxConcurrentSessions: 2, maxConcurrentSessionsPerActor: 1 }),
      copilot,
      tokenService,
      new MemoryChatStore(),
    );
    await runtime.start("actor-a", "First", () => undefined);
    await expect(runtime.start("actor-a", "Second", () => undefined)).rejects.toThrow(/per-actor/);
    await runtime.start("actor-b", "Second actor", () => undefined);
    await expect(runtime.start("actor-c", "Third actor", () => undefined)).rejects.toThrow(
      /concurrency limit/,
    );
  });

  it("returns the session id before send admission and can cancel immediately", async () => {
    let releaseSend: (() => void) | undefined;
    const copilot = new FakeCopilotRuntime();
    copilot.sendGate = new Promise<void>((resolve) => {
      releaseSend = resolve;
    });
    const runtime = new ChatRuntime(
      syntheticConfig(),
      copilot,
      tokenService,
      new MemoryChatStore(),
    );
    const sessionId = await Promise.race([
      runtime.start("actor-a", "Safe question", () => undefined),
      new Promise<never>((_resolve, reject) =>
        setTimeout(() => reject(new Error("start waited for send")), 50),
      ),
    ]);
    await runtime.cancel("actor-a", sessionId);
    releaseSend?.();
    await vi.waitFor(() =>
      expect(copilot.runs.get(sessionId)).toMatchObject({ aborted: true, closed: true }),
    );
  });

  it("serializes evidence before one terminal event and ignores concurrent idle", async () => {
    const copilot = new FakeCopilotRuntime();
    const runtime = new ChatRuntime(
      syntheticConfig(),
      copilot,
      tokenService,
      new MemoryChatStore(),
    );
    const events: StreamEvent[] = [];
    const sessionId = await runtime.start("actor-a", "Safe question", (event) =>
      events.push(event),
    );
    await vi.waitFor(() => expect(copilot.runs.has(sessionId)).toBe(true));
    copilot.emit(sessionId, {
      ...eventBase("tool.execution_start"),
      type: "tool.execution_start",
      data: {
        toolName: "penge-get_source_coverage",
        mcpToolName: "get_source_coverage",
        mcpConfigServerName: "penge",
        toolCallId: "call-1",
        arguments: {},
      },
    });

    copilot.emit(sessionId, {
      ...eventBase("tool.execution_complete"),
      type: "tool.execution_complete",
      data: {
        success: true,
        toolCallId: "call-1",
        result: {
          content: "redacted",
          structuredContent: {
            complete: false,
            sources: [
              {
                id: "nordnet",
                coverage: { completeness: "partial", freshness: "fresh" },
              },
            ],
          },
        },
      },
    });
    const idle: SessionEvent = {
      ...eventBase("session.idle"),
      type: "session.idle",
      ephemeral: true,
      data: { aborted: false },
    };
    copilot.emit(sessionId, idle);
    copilot.emit(sessionId, idle);

    await vi.waitFor(() =>
      expect(events.filter((event) => event.type === "completion")).toHaveLength(1),
    );
    expect(events.map((event) => event.type)).toEqual(["tool", "tool", "evidence", "completion"]);
    expect(events[2]).toMatchObject({
      type: "evidence",
      source: "nordnet",
      coverage: "partial",
      freshness: "fresh",
      currency: "mixed",
    });
  });

  it("derives evidence only from declared metadata keys", () => {
    expect(
      projectEvidence("query_net_worth", {
        result: [
          {
            description: "missing fresh nordnet DKK",
            currency: "EUR",
          },
        ],
      }),
    ).toMatchObject({
      source: "Penge MCP: query_net_worth",
      coverage: "partial",
      freshness: "missing",
      currency: "EUR",
    });
  });

  it.each([
    ["no evidence", [], { coverage: "partial", freshness: "stale" }],
    [
      "all full and fresh",
      [
        { coverage: "full" as const, freshness: "fresh" as const },
        { coverage: "full" as const, freshness: "fresh" as const },
      ],
      { coverage: "full", freshness: "fresh" },
    ],
    [
      "mixed partial and stale",
      [
        { coverage: "full" as const, freshness: "fresh" as const },
        { coverage: "partial" as const, freshness: "stale" as const },
      ],
      { coverage: "partial", freshness: "stale" },
    ],
    [
      "missing evidence",
      [{ coverage: "missing" as const, freshness: "missing" as const }],
      { coverage: "partial", freshness: "stale" },
    ],
  ])("summarizes %s conservatively", (_name, evidence, expected) => {
    expect(summarizeEvidence(evidence)).toEqual(expected);
  });

  it("continues close and audit when the terminal sink throws", async () => {
    const copilot = new FakeCopilotRuntime();
    const store = new MemoryChatStore();
    const runtime = new ChatRuntime(syntheticConfig(), copilot, tokenService, store);
    const sessionId = await runtime.start("actor-a", "Safe question", (event) => {
      if (event.type === "completion") throw new Error("synthetic disconnected sink");
    });
    await vi.waitFor(() => expect(copilot.runs.has(sessionId)).toBe(true));
    await expect(runtime.cancel("actor-a", sessionId)).rejects.toThrow(/cleanup failed/);
    expect(copilot.runs.get(sessionId)).toMatchObject({ aborted: true, closed: true });
    expect(store.audits.filter((event) => event.status === "cancelled")).toHaveLength(1);
  });

  it("emits one terminal event when abort concurrently reports idle", async () => {
    const copilot = new FakeCopilotRuntime();
    copilot.emitIdleOnAbort = true;
    const runtime = new ChatRuntime(
      syntheticConfig(),
      copilot,
      tokenService,
      new MemoryChatStore(),
    );
    const events: StreamEvent[] = [];
    const sessionId = await runtime.start("actor-a", "Safe question", (event) => {
      events.push(event);
    });
    await vi.waitFor(() => expect(copilot.runs.has(sessionId)).toBe(true));

    await runtime.cancel("actor-a", sessionId);
    expect(events.filter((event) => event.type === "completion")).toHaveLength(1);
    expect(runtime.activeSessionCount).toBe(0);
  });

  it("emits a cancelled completion when link invalidation stops an active run", async () => {
    const copilot = new FakeCopilotRuntime();
    const runtime = new ChatRuntime(
      syntheticConfig(),
      copilot,
      tokenService,
      new MemoryChatStore(),
    );
    const events: StreamEvent[] = [];
    const sessionId = await runtime.start("actor-a", "Safe question", (event) => {
      events.push(event);
    });
    await vi.waitFor(() => expect(copilot.runs.has(sessionId)).toBe(true));

    await runtime.invalidateActor("actor-a");
    expect(events.filter((event) => event.type === "completion")).toEqual([
      expect.objectContaining({ finishReason: "cancelled" }),
    ]);
    expect(copilot.runs.get(sessionId)).toMatchObject({ aborted: true, closed: true });
    expect(runtime.activeSessionCount).toBe(0);
  });

  it("propagates request timeout to process cleanup", async () => {
    vi.useFakeTimers();
    const copilot = new FakeCopilotRuntime();
    const runtime = new ChatRuntime(
      syntheticConfig({ requestTimeoutMs: 25 }),
      copilot,
      tokenService,
      new MemoryChatStore(),
    );
    const sessionId = await runtime.start("actor-a", "Safe question", () => undefined);
    await vi.advanceTimersByTimeAsync(25);
    expect(copilot.runs.get(sessionId)).toMatchObject({ aborted: true, closed: true });
    expect(runtime.activeSessionCount).toBe(0);
  });

  it("drains every session when audit and run cleanup reject", async () => {
    class RejectingAuditStore extends MemoryChatStore {
      override async appendAudit(
        event: Parameters<MemoryChatStore["appendAudit"]>[0],
      ): Promise<void> {
        if (event.status !== "started") {
          throw new Error("synthetic audit failure");
        }
        await super.appendAudit(event);
      }
    }

    const copilot = new FakeCopilotRuntime();
    copilot.closeError = new Error("synthetic close failure");
    const runtime = new ChatRuntime(
      syntheticConfig(),
      copilot,
      tokenService,
      new RejectingAuditStore(),
    );
    const first = await runtime.start("actor-a", "Safe question", () => undefined);
    const second = await runtime.start("actor-b", "Another safe question", () => undefined);
    await vi.waitFor(() => expect(copilot.runs.size).toBe(2));

    await expect(runtime.close()).rejects.toThrow(/background lifecycle failures/);
    expect(copilot.runs.get(first)).toMatchObject({ aborted: true, closed: true });
    expect(copilot.runs.get(second)).toMatchObject({ aborted: true, closed: true });
    expect(runtime.activeSessionCount).toBe(0);
  });
});

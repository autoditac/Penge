import { createConnection } from "node:net";
import { Writable } from "node:stream";

import pino from "pino";
import { describe, expect, it, vi } from "vitest";

import { FeatureDisabledError, PengeError, SessionLimitError } from "../src/errors.js";
import { startChatServer } from "../src/server.js";
import type { StreamEvent } from "../src/stream.js";
import { syntheticConfig } from "./helpers.js";

const headers = {
  "content-type": "application/json",
  origin: "https://penge.example.test",
  "x-penge-proxy-secret": "p".repeat(32),
  "x-penge-auth-issuer": "https://accounts.google.com",
  "x-penge-auth-subject": "synthetic-google-subject",
};

describe("loopback HTTP service", () => {
  it("binds loopback, rejects direct requests, and streams terminal events", async () => {
    const runtime = {
      start: async (_actorId: string, _question: string, sink: (event: StreamEvent) => void) => {
        sink({
          version: "1.0",
          sessionId: "00000000-0000-4000-8000-000000000001",
          id: "event-1",
          sequence: 0,
          type: "completion",
          summary: "Synthetic completion",
          coverage: "partial",
          freshness: "fresh",
          finishReason: "completed",
          assumptions: [],
        });
        return "00000000-0000-4000-8000-000000000001";
      },
      cancel: async () => undefined,
      disconnect: async () => undefined,
      cleanupIdle: async () => 0,
      close: async () => undefined,
      isModelAvailable: () => true,
      ensureModelAvailable: async () => true,
      invalidateActor: async () => undefined,
    };
    const server = await startChatServer(syntheticConfig(), {
      runtime,
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "linked" as const, login: "synthetic-user" }),
        unlink: async () => undefined,
      },
    });
    try {
      expect(server.origin).toMatch(/^http:\/\/127\.0\.0\.1:/);
      const direct = await fetch(`${server.origin}/v1/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: "Safe question" }),
      });
      expect(direct.status).toBe(401);

      const response = await fetch(`${server.origin}/v1/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({ question: "Safe question" }),
      });
      expect(response.status).toBe(200);
      expect(await response.text()).toContain('"type":"completion"');
    } finally {
      await server.close();
    }
  });

  it("returns an explicit unavailable response before starting an SSE stream", async () => {
    const server = await startChatServer(syntheticConfig({ productionEnabled: false }), {
      runtime: {
        start: async () => {
          throw new FeatureDisabledError("disabled");
        },
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => false,
        ensureModelAvailable: async () => false,
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "linked" as const, login: "synthetic-user" }),
        unlink: async () => undefined,
      },
    });
    try {
      const response = await fetch(`${server.origin}/v1/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({ question: "Safe question" }),
      });
      expect(response.status).toBe(503);
      expect(await response.json()).toEqual({
        code: "hydrafusion_unavailable",
        message: "Ask Penge is not enabled.",
      });
    } finally {
      await server.close();
    }
  });

  it("publishes strict per-actor status, callback, and unlink routes", async () => {
    let linked = true;
    let modelAvailable = true;
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => "00000000-0000-4000-8000-000000000001",
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => modelAvailable,
        ensureModelAvailable: async () => modelAvailable,
        invalidateActor: async () => {
          modelAvailable = false;
        },
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () =>
          linked
            ? { state: "linked" as const, login: "synthetic-user" }
            : { state: "not-linked" as const, login: null },
        unlink: async () => {
          linked = false;
        },
      },
    });
    try {
      const status = await fetch(`${server.origin}/v1/auth/status`, { headers });
      expect(await status.json()).toEqual({
        github: { state: "linked", login: "synthetic-user" },
        model: { id: "hydrafusion", available: true },
        featureEnabled: true,
      });

      const callback = await fetch(
        `${server.origin}/oauth/github/callback?state=synthetic-state&code=synthetic-code`,
        { headers, redirect: "manual" },
      );
      expect(callback.headers.get("location")).toBe("https://penge.example.test/ask?github=linked");

      const unlink = await fetch(`${server.origin}/v1/auth/github`, {
        method: "DELETE",
        headers,
      });
      expect(await unlink.json()).toEqual({ status: "unlinked" });
      const unlinkedStatus = await fetch(`${server.origin}/v1/auth/status`, { headers });
      expect(await unlinkedStatus.json()).toEqual({
        github: { state: "not-linked", login: null },
        model: { id: "hydrafusion", available: false },
        featureEnabled: true,
      });
    } finally {
      await server.close();
    }
  });

  it("returns rate_limit when model readiness has no shared capacity", async () => {
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => "00000000-0000-4000-8000-000000000001",
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => false,
        ensureModelAvailable: async () => {
          throw new SessionLimitError("capacity is full");
        },
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "linked" as const, login: "synthetic-user" }),
        unlink: async () => undefined,
      },
    });
    try {
      const response = await fetch(`${server.origin}/v1/auth/status`, { headers });
      expect(response.status).toBe(429);
      expect(await response.json()).toEqual({
        code: "rate_limit",
        message: "The chat concurrency limit was reached.",
      });
    } finally {
      await server.close();
    }
  });

  it("closes the listener even when runtime cleanup fails", async () => {
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => "00000000-0000-4000-8000-000000000001",
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => {
          throw new Error("synthetic runtime cleanup failure");
        },
        isModelAvailable: () => false,
        ensureModelAvailable: async () => false,
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "not-linked" as const, login: null }),
        unlink: async () => undefined,
      },
    });
    await expect(server.close()).rejects.toThrow(/chat server cleanup failed/);
    await expect(fetch(`${server.origin}/health`)).rejects.toThrow();
  });

  it("does not expose internal PengeError messages", async () => {
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => {
          throw new PengeError("chat/internal", "synthetic secret diagnostic");
        },
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => false,
        ensureModelAvailable: async () => false,
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "linked" as const, login: "synthetic-user" }),
        unlink: async () => undefined,
      },
    });

    try {
      const response = await fetch(`${server.origin}/v1/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({ question: "Safe question" }),
      });
      expect(response.status).toBe(400);
      const body = JSON.stringify(await response.json());
      expect(body).toContain("invalid_request");
      expect(body).not.toContain("synthetic secret diagnostic");
    } finally {
      await server.close();
    }
  });

  it("rejects cross-origin mutations and non-JSON chat bodies", async () => {
    const runtimeStart = vi.fn(
      async (_actorId: string, _question: string, sink: (event: StreamEvent) => void) => {
        sink({
          version: "1.0",
          sessionId: "00000000-0000-4000-8000-000000000001",
          id: "event-unicode",
          sequence: 0,
          type: "completion",
          summary: "Synthetic completion",
          coverage: "partial",
          freshness: "stale",
          finishReason: "completed",
          assumptions: [],
        });
        return "00000000-0000-4000-8000-000000000001";
      },
    );
    const unlink = vi.fn(async () => undefined);
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: runtimeStart,
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => true,
        ensureModelAvailable: async () => true,
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "linked" as const, login: "synthetic-user" }),
        unlink,
      },
    });
    try {
      const crossOrigin = await fetch(`${server.origin}/v1/chat`, {
        method: "POST",
        headers: { ...headers, origin: "https://attacker.example.test" },
        body: JSON.stringify({ question: "Safe question" }),
      });
      expect(crossOrigin.status).toBe(403);

      const crossOriginDelete = await fetch(`${server.origin}/v1/auth/github`, {
        method: "DELETE",
        headers: { ...headers, origin: "https://attacker.example.test" },
      });
      expect(crossOriginDelete.status).toBe(403);

      const formCompatible = await fetch(`${server.origin}/v1/chat`, {
        method: "POST",
        headers: { ...headers, "content-type": "text/plain" },
        body: JSON.stringify({ question: "Safe question" }),
      });
      expect(formCompatible.status).toBe(415);
      expect(runtimeStart).not.toHaveBeenCalled();
      expect(unlink).not.toHaveBeenCalled();

      const unicodeQuestion = "界".repeat(8_000);
      const unicode = await fetch(`${server.origin}/v1/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({ question: unicodeQuestion }),
      });
      expect(unicode.status).toBe(200);
      expect(runtimeStart).toHaveBeenCalledWith(
        expect.any(String),
        unicodeQuestion,
        expect.any(Function),
      );
    } finally {
      await server.close();
    }
  });

  it("logs only fixed route identifiers for caller-controlled paths", async () => {
    let logs = "";
    const destination = new Writable({
      write(chunk, _encoding, callback) {
        logs += chunk.toString();
        callback();
      },
    });
    const server = await startChatServer(syntheticConfig(), {
      logger: pino({ level: "info" }, destination),
      runtime: {
        start: async () => "00000000-0000-4000-8000-000000000001",
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => false,
        ensureModelAvailable: async () => false,
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "not-linked" as const, login: null }),
        unlink: async () => undefined,
      },
    });
    try {
      await fetch(`${server.origin}/v1/chat/synthetic-sensitive-value`);
      expect(logs).toContain('"route":"unrecognized"');
      expect(logs).not.toContain("synthetic-sensitive-value");
    } finally {
      await server.close();
    }
  });

  it("rejects malformed request targets without terminating the listener", async () => {
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => "00000000-0000-4000-8000-000000000001",
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => false,
        ensureModelAvailable: async () => false,
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "not-linked" as const, login: null }),
        unlink: async () => undefined,
      },
    });
    try {
      const target = new URL(server.origin);
      const response = await new Promise<string>((resolve, reject) => {
        const socket = createConnection(Number(target.port), target.hostname);
        let received = "";
        socket.setEncoding("utf8");
        socket.once("error", reject);
        socket.on("data", (chunk: string) => {
          received += chunk;
        });
        socket.once("end", () => resolve(received));
        socket.once("connect", () => {
          socket.end(`GET //[ HTTP/1.1\r\nHost: ${target.host}\r\nConnection: close\r\n\r\n`);
        });
      });
      expect(response).toContain("400 Bad Request");
      expect(response).toContain('"code":"invalid_request"');
      await expect(fetch(`${server.origin}/health`)).resolves.toMatchObject({ status: 200 });
    } finally {
      await server.close();
    }
  });

  it("probes exact-model readiness after linking before the first question", async () => {
    let linked = false;
    let probes = 0;
    let starts = 0;
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async (_actorId, _question, sink) => {
          starts += 1;
          sink({
            version: "1.0",
            sessionId: "00000000-0000-4000-8000-000000000001",
            id: "event-1",
            sequence: 0,
            type: "completion",
            summary: "Synthetic completion",
            coverage: "partial",
            freshness: "stale",
            finishReason: "completed",
            assumptions: [],
          });
          return "00000000-0000-4000-8000-000000000001";
        },
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => probes > 0,
        ensureModelAvailable: async () => {
          probes += 1;
          return true;
        },
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => {
          linked = true;
          return "synthetic-user";
        },
        status: async () =>
          linked
            ? { state: "linked" as const, login: "synthetic-user" }
            : { state: "not-linked" as const, login: null },
        unlink: async () => undefined,
      },
    });
    try {
      const callback = await fetch(
        `${server.origin}/oauth/github/callback?state=synthetic-state&code=synthetic-code`,
        { headers, redirect: "manual" },
      );
      expect(callback.status).toBe(302);
      const status = await fetch(`${server.origin}/v1/auth/status`, { headers });
      expect(await status.json()).toMatchObject({
        github: { state: "linked" },
        model: { id: "hydrafusion", available: true },
      });
      expect(probes).toBe(1);

      const chat = await fetch(`${server.origin}/v1/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({ question: "First linked question" }),
      });
      expect(chat.status).toBe(200);
      expect(starts).toBe(1);
    } finally {
      await server.close();
    }
  });

  it("flushes the session id before the first stream event", async () => {
    const disconnect = vi.fn(async () => undefined);
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => "00000000-0000-4000-8000-000000000001",
        cancel: async () => undefined,
        disconnect,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => true,
        ensureModelAvailable: async () => true,
        invalidateActor: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
        status: async () => ({ state: "linked" as const, login: "synthetic-user" }),
        unlink: async () => undefined,
      },
    });
    const controller = new AbortController();
    try {
      const response = await Promise.race([
        fetch(`${server.origin}/v1/chat`, {
          method: "POST",
          headers,
          body: JSON.stringify({ question: "Delayed first event" }),
          signal: controller.signal,
        }),
        new Promise<never>((_resolve, reject) =>
          setTimeout(() => reject(new Error("session headers were not flushed")), 100),
        ),
      ]);
      expect(response.headers.get("x-penge-chat-session-id")).toBe(
        "00000000-0000-4000-8000-000000000001",
      );
    } finally {
      controller.abort();
      await vi.waitFor(() => expect(disconnect).toHaveBeenCalledOnce());
      await server.close();
    }
  });
});

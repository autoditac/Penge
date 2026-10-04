import { describe, expect, it } from "vitest";

import { FeatureDisabledError, PengeError } from "../src/errors.js";
import { startChatServer } from "../src/server.js";
import type { StreamEvent } from "../src/stream.js";
import { syntheticConfig } from "./helpers.js";

const headers = {
  "content-type": "application/json",
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
});

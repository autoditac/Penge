import { describe, expect, it } from "vitest";

import { FeatureDisabledError } from "../src/errors.js";
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
        });
        return "00000000-0000-4000-8000-000000000001";
      },
      cancel: async () => undefined,
      disconnect: async () => undefined,
      cleanupIdle: async () => 0,
      close: async () => undefined,
    };
    const server = await startChatServer(syntheticConfig(), {
      runtime,
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
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
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => {
          throw new FeatureDisabledError("disabled");
        },
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async () => "synthetic-user",
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
});

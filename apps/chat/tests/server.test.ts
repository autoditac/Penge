import { spawn } from "node:child_process";
import { once } from "node:events";
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { createServer, request, ServerResponse } from "node:http";
import { createConnection, createServer as createTcpServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { Writable } from "node:stream";

import pino from "pino";
import { describe, expect, it, vi } from "vitest";

import {
  AuthenticationError,
  FeatureDisabledError,
  PengeError,
  SessionLimitError,
} from "../src/errors.js";
import { bindTrustedIdentity, exchangeGitHubCode, generateOAuthState } from "../src/identity.js";
import { closeServiceResources } from "../src/lifecycle.js";
import { startChatServer, type ChatServerDependencies } from "../src/server.js";
import type { StreamEvent } from "../src/stream.js";
import { syntheticConfig } from "./helpers.js";

const headers = {
  "content-type": "application/json",
  origin: "https://penge.example.test",
  "x-penge-proxy-secret": "p".repeat(32),
  "x-penge-auth-issuer": "https://accounts.google.com",
  "x-penge-auth-subject": "synthetic-google-subject",
};

function socketDependencies(): ChatServerDependencies {
  return {
    runtime: {
      start: async () => "00000000-0000-4000-8000-000000000001",
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
      unlink: async () => undefined,
    },
  };
}

function socketStatus(socketPath: string, requestHeaders: Record<string, string>): Promise<number> {
  return new Promise((resolve, reject) => {
    const req = request({ socketPath, path: "/v1/auth/status", headers: requestHeaders }, (res) => {
      res.resume();
      res.once("end", () => resolve(res.statusCode ?? 0));
    });
    req.once("error", reject);
    req.end();
  });
}

describe("Unix socket service", () => {
  it("uses only the permissioned socket and still authenticates proxy headers", async () => {
    const directory = mkdtempSync(join(tmpdir(), "penge-chat-socket-"));
    chmodSync(directory, 0o2750);
    const socketPath = join(directory, "chat.sock");
    const sentinel = createTcpServer();
    await new Promise<void>((resolve) => sentinel.listen(0, "127.0.0.1", resolve));
    const address = sentinel.address();
    if (address === null || typeof address === "string") throw new Error("no test TCP port");
    const port = address.port;
    await new Promise<void>((resolve, reject) =>
      sentinel.close((error) => (error ? reject(error) : resolve())),
    );
    const server = await startChatServer(
      syntheticConfig({ httpSocketPath: socketPath, httpPort: port }),
      socketDependencies(),
    );
    try {
      expect(server.origin).toMatch(/^http\+unix:/);
      expect(lstatSync(socketPath).mode & 0o777).toBe(0o660);
      expect(lstatSync(socketPath).gid).toBe(lstatSync(directory).gid);
      expect(await socketStatus(socketPath, {})).toBe(401);
      expect(await socketStatus(socketPath, { ...headers, "x-penge-proxy-secret": "wrong" })).toBe(
        401,
      );
      expect(await socketStatus(socketPath, headers)).toBe(200);
      await expect(
        fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(200) }),
      ).rejects.toThrow();
    } finally {
      await server.close();
      rmSync(directory, { recursive: true, force: true });
    }
  });

  it("rejects unsafe directories and existing files, symlinks, and live sockets", async () => {
    const directory = mkdtempSync(join(tmpdir(), "penge-chat-socket-"));
    const socketPath = join(directory, "chat.sock");
    const config = syntheticConfig({ httpSocketPath: socketPath });
    try {
      await expect(startChatServer(config, socketDependencies())).rejects.toThrow(/mode 2750/);
      chmodSync(directory, 0o2750);
      writeFileSync(socketPath, "synthetic");
      await expect(startChatServer(config, socketDependencies())).rejects.toThrow(/already exists/);
      expect(lstatSync(socketPath).isFile()).toBe(true);
      rmSync(socketPath);
      symlinkSync("/nonexistent", socketPath);
      await expect(startChatServer(config, socketDependencies())).rejects.toThrow(/already exists/);
      expect(lstatSync(socketPath).isSymbolicLink()).toBe(true);
      rmSync(socketPath);
      const live = createTcpServer();
      await new Promise<void>((resolve) => live.listen(socketPath, resolve));
      try {
        await expect(startChatServer(config, socketDependencies())).rejects.toThrow(
          /already exists/,
        );
        expect(lstatSync(socketPath).isSocket()).toBe(true);
      } finally {
        await new Promise<void>((resolve, reject) =>
          live.close((error) => (error ? reject(error) : resolve())),
        );
      }
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  it("does not remove a stale socket left by an abruptly stopped process", async () => {
    const directory = mkdtempSync(join(tmpdir(), "penge-chat-stale-"));
    chmodSync(directory, 0o2750);
    const socketPath = join(directory, "chat.sock");
    const child = spawn(
      process.execPath,
      [
        "-e",
        "require('node:net').createServer().listen(process.argv[1], () => process.stdout.write('ready'))",
        socketPath,
      ],
      { stdio: ["ignore", "pipe", "pipe"] },
    );
    try {
      await once(child.stdout, "data");
      child.kill("SIGKILL");
      await once(child, "exit");
      expect(lstatSync(socketPath).isSocket()).toBe(true);
      await expect(
        startChatServer(syntheticConfig({ httpSocketPath: socketPath }), socketDependencies()),
      ).rejects.toThrow(/already exists/);
      expect(lstatSync(socketPath).isSocket()).toBe(true);
    } finally {
      if (child.exitCode === null && child.signalCode === null) {
        child.kill("SIGKILL");
        await once(child, "exit");
      }
      rmSync(directory, { recursive: true, force: true });
    }
  });

  it.skipIf(process.env.PENGE_TEST_NGINX === undefined)(
    "routes nginx to the socket and overwrites spoofed identity headers",
    async () => {
      const directory = mkdtempSync(join(tmpdir(), "penge-chat-proxy-"));
      chmodSync(directory, 0o2750);
      mkdirSync(join(directory, "logs"));
      const socketPath = join(directory, "chat.sock");
      const config = syntheticConfig({ httpSocketPath: socketPath });
      const dependencies = socketDependencies();
      let actualActor = "";
      dependencies.oauth.status = async (actorId) => {
        actualActor = actorId;
        return { state: "linked", login: "synthetic-user" };
      };
      const chat = await startChatServer(config, dependencies);
      const auth = createServer((_req, res) => {
        res.writeHead(204);
        res.end();
      });
      await new Promise<void>((done) => auth.listen(0, "127.0.0.1", done));
      const authAddress = auth.address();
      if (authAddress === null || typeof authAddress === "string") throw new Error("no auth port");
      const portProbe = createTcpServer();
      await new Promise<void>((done) => portProbe.listen(0, "127.0.0.1", done));
      const portAddress = portProbe.address();
      if (portAddress === null || typeof portAddress === "string") throw new Error("no proxy port");
      await new Promise<void>((done, reject) =>
        portProbe.close((error) => (error ? reject(error) : done())),
      );
      let template = readFileSync(
        resolve(process.cwd(), "../../deploy/nas/penge-chat.nginx.conf.in"),
        "utf8",
      );
      for (const [from, to] of Object.entries({
        "127.0.0.1:4180": `127.0.0.1:${authAddress.port}`,
        "@@CHAT_SOCKET_HOST_DIR@@": directory,
        "@@IMMUTABLE_AUTH_SUBJECT_NGINX_VALUE@@": headers["x-penge-auth-subject"],
        "@@TRUSTED_PROXY_ISSUER_NGINX_VALUE@@": headers["x-penge-auth-issuer"],
        "@@MOUNTED_PROXY_SECRET_NGINX_VALUE@@": headers["x-penge-proxy-secret"],
        "@@STREAMING_READ_TIMEOUT@@": "30s",
        "@@STREAMING_REQUEST_BUFFERING@@": "off",
        "@@STREAMING_RESPONSE_BUFFERING@@": "off",
        "@@STREAMING_SEND_TIMEOUT@@": "30s",
      })) {
        template = template.replaceAll(from, to);
      }
      const nginxConfig = join(directory, "nginx.conf");
      writeFileSync(
        nginxConfig,
        `daemon off;\nmaster_process off;\npid ${directory}/nginx.pid;\nerror_log ${directory}/error.log;\nevents {}\nhttp { server { listen 127.0.0.1:${portAddress.port};\n${template}\n} }\n`,
      );
      const nginx = spawn(process.env.PENGE_TEST_NGINX!, ["-p", directory, "-c", nginxConfig], {
        stdio: "ignore",
      });
      try {
        let response: Response | undefined;
        for (let attempt = 0; attempt < 100; attempt++) {
          try {
            response = await fetch(`http://127.0.0.1:${portAddress.port}/ask/api/v1/auth/status`, {
              headers: {
                ...headers,
                "x-penge-auth-subject": "spoofed-subject",
                "x-penge-auth-issuer": "spoofed-issuer",
                "x-penge-proxy-secret": "spoofed-secret",
              },
            });
            break;
          } catch {
            if (nginx.exitCode !== null) throw new Error("synthetic nginx exited");
            await new Promise((done) => setTimeout(done, 20));
          }
        }
        expect(response?.status).toBe(200);
        expect(actualActor).toBe(
          bindTrustedIdentity(
            headers,
            config.trustedProxyIssuer,
            config.identityPepper,
            config.proxySharedSecret,
          ).actorId,
        );
        expect(await socketStatus(socketPath, {})).toBe(401);
      } finally {
        if (nginx.exitCode === null && nginx.signalCode === null) {
          nginx.kill("SIGTERM");
          await once(nginx, "exit");
        }
        await new Promise<void>((done, reject) =>
          auth.close((error) => (error ? reject(error) : done())),
        );
        await chat.close();
        rmSync(directory, { recursive: true, force: true });
      }
    },
  );
});

describe("loopback HTTP service", () => {
  it("binds loopback, rejects direct requests, and streams terminal events", async () => {
    const disconnect = vi.fn(async () => undefined);
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
      disconnect,
      cleanupIdle: async () => 0,
      close: async () => undefined,
      isModelAvailable: () => true,
      ensureModelAvailable: async () => true,
      invalidateActor: async () => undefined,
    };
    const server = await startChatServer(syntheticConfig({ httpRequestTimeoutMs: 100 }), {
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
      await new Promise((resolve) => setTimeout(resolve, 150));
      expect(disconnect).not.toHaveBeenCalled();
    } finally {
      await server.close();
    }
  });

  it.each(["active", "completed"] as const)(
    "disconnects a stalled %s SSE stream after the bounded drain deadline",
    async (state) => {
      let sink: ((event: StreamEvent) => void) | undefined;
      const disconnect = vi.fn(async () => undefined);
      const write = vi.spyOn(ServerResponse.prototype, "write").mockReturnValue(false);
      const sessionId = "00000000-0000-4000-8000-000000000001";
      const server = await startChatServer(syntheticConfig({ httpRequestTimeoutMs: 25 }), {
        runtime: {
          start: async (_actorId, _question, eventSink) => {
            sink = eventSink;
            return sessionId;
          },
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
      try {
        const response = await fetch(`${server.origin}/v1/chat`, {
          method: "POST",
          headers,
          body: JSON.stringify({ question: "Safe question" }),
        });
        expect(response.status).toBe(200);
        if (sink === undefined) throw new Error("stream sink was not registered");
        sink({
          version: "1.0",
          sessionId,
          id: "event-1",
          sequence: 0,
          type: "text",
          stream: "answer",
          delta: "Synthetic answer",
          source: "assistant",
        });
        if (state === "completed") {
          sink({
            version: "1.0",
            sessionId,
            id: "event-2",
            sequence: 1,
            type: "completion",
            summary: "Synthetic completion",
            coverage: "partial",
            freshness: "stale",
            finishReason: "completed",
            assumptions: [],
          });
        }
        await vi.waitFor(() => expect(disconnect).toHaveBeenCalledOnce(), { timeout: 500 });
        expect(disconnect).toHaveBeenCalledWith(expect.any(String), sessionId);
      } finally {
        write.mockRestore();
        await server.close();
      }
    },
  );

  it.each(["accepted", "drained"] as const)(
    "bounds an unfinished terminal SSE response after its write is %s",
    async (delivery) => {
      let sink: ((event: StreamEvent) => void) | undefined;
      const disconnect = vi.fn(async () => undefined);
      const write = vi
        .spyOn(ServerResponse.prototype, "write")
        .mockReturnValue(delivery === "accepted");
      const end = vi.spyOn(ServerResponse.prototype, "end").mockImplementation(function (
        this: ServerResponse,
      ) {
        return this;
      });
      const sessionId = "00000000-0000-4000-8000-000000000001";
      const server = await startChatServer(syntheticConfig({ httpRequestTimeoutMs: 100 }), {
        runtime: {
          start: async (_actorId, _question, eventSink) => {
            sink = eventSink;
            return sessionId;
          },
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
      try {
        const response = await fetch(`${server.origin}/v1/chat`, {
          method: "POST",
          headers,
          body: JSON.stringify({ question: "Safe question" }),
        });
        expect(response.status).toBe(200);
        if (sink === undefined) throw new Error("stream sink was not registered");
        sink({
          version: "1.0",
          sessionId,
          id: "event-1",
          sequence: 0,
          type: "completion",
          summary: "Synthetic completion",
          coverage: "partial",
          freshness: "fresh",
          finishReason: "completed",
          assumptions: [],
        });
        const outbound = write.mock.contexts[0];
        if (!(outbound instanceof ServerResponse)) {
          throw new Error("terminal write was not attempted");
        }
        if (delivery === "drained") outbound.emit("drain");
        expect(end).toHaveBeenCalledOnce();
        expect(outbound.writableFinished).toBe(false);
        await vi.waitFor(() => expect(disconnect).toHaveBeenCalledOnce(), {
          timeout: 1_000,
          interval: 10,
        });
        expect(outbound.destroyed).toBe(true);
        expect(disconnect).toHaveBeenCalledWith(expect.any(String), sessionId);
      } finally {
        write.mockRestore();
        end.mockRestore();
        await server.close();
      }
    },
  );

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

  it("returns auth_expired when readiness hits a rejected token refresh", async () => {
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => "00000000-0000-4000-8000-000000000001",
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => false,
        ensureModelAvailable: async () => {
          throw new AuthenticationError("GitHub rejected the refresh token");
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
      expect(response.status).toBe(401);
      expect(await response.json()).toMatchObject({ code: "auth_expired" });
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

  it.each(["status", "chat"] as const)(
    "drains a delayed %s handler before runtime and store shutdown",
    async (route) => {
      let releaseStatus: (() => void) | undefined;
      let signalStatus: (() => void) | undefined;
      const statusEntered = new Promise<void>((resolve) => {
        signalStatus = resolve;
      });
      const statusGate = new Promise<void>((resolve) => {
        releaseStatus = resolve;
      });
      const start = vi.fn(async () => "00000000-0000-4000-8000-000000000001");
      const ensureModelAvailable = vi.fn(async () => true);
      const closeRuntime = vi.fn(async () => undefined);
      const closeStore = vi.fn(async () => undefined);
      const server = await startChatServer(syntheticConfig(), {
        runtime: {
          start,
          cancel: async () => undefined,
          disconnect: async () => undefined,
          cleanupIdle: async () => 0,
          close: closeRuntime,
          isModelAvailable: () => false,
          ensureModelAvailable,
          invalidateActor: async () => undefined,
        },
        oauth: {
          begin: async () => "https://github.com/login/oauth/authorize",
          complete: async () => "synthetic-user",
          status: async () => {
            signalStatus?.();
            await statusGate;
            return { state: "linked" as const, login: "synthetic-user" };
          },
          unlink: async () => undefined,
        },
      });
      const request =
        route === "status"
          ? fetch(`${server.origin}/v1/auth/status`, { headers }).catch(() => undefined)
          : fetch(`${server.origin}/v1/chat`, {
              method: "POST",
              headers,
              body: JSON.stringify({ question: "Safe question" }),
            }).catch(() => undefined);
      await statusEntered;
      const closing = closeServiceResources(server, { close: closeStore });
      try {
        await request;
        const state = await Promise.race([
          closing.then(() => "closed"),
          new Promise<"pending">((resolve) => setTimeout(() => resolve("pending"), 50)),
        ]);
        expect(state).toBe("pending");
        expect(closeRuntime).not.toHaveBeenCalled();
        expect(closeStore).not.toHaveBeenCalled();
      } finally {
        releaseStatus?.();
        await closing;
      }
      expect(start).not.toHaveBeenCalled();
      expect(ensureModelAvailable).not.toHaveBeenCalled();
      expect(closeRuntime).toHaveBeenCalledOnce();
      expect(closeStore).toHaveBeenCalledOnce();
    },
  );

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

  it("maps expired GitHub authorization codes to 401 and malformed upstream bodies to 502", async () => {
    const tokenResponses = [
      Response.json({
        error: "bad_verification_code",
        error_description: "synthetic-upstream-marker",
      }),
      Response.json({ token_type: "bearer" }),
      new Response("{invalid", { headers: { "content-type": "application/json" } }),
      new Response("synthetic outage", { status: 503 }),
    ];
    const oauthConfig = {
      clientId: "client",
      clientSecret: "secret",
      authorizeUrl: "https://github.com/login/oauth/authorize",
      tokenUrl: "https://github.com/login/oauth/access_token",
      apiUrl: "https://api.github.com",
    };
    const invalidateActor = vi.fn(async () => undefined);
    const server = await startChatServer(syntheticConfig(), {
      runtime: {
        start: async () => "00000000-0000-4000-8000-000000000001",
        cancel: async () => undefined,
        disconnect: async () => undefined,
        cleanupIdle: async () => 0,
        close: async () => undefined,
        isModelAvailable: () => true,
        ensureModelAvailable: async () => true,
        invalidateActor,
      },
      oauth: {
        begin: async () => "https://github.com/login/oauth/authorize",
        complete: async (actorId, _state, code) => {
          const state = generateOAuthState(actorId, "https://penge.example.test/cb");
          await exchangeGitHubCode(oauthConfig, code, state, async () => tokenResponses.shift()!);
          return "synthetic-user";
        },
        status: async () => ({ state: "not-linked" as const, login: null }),
        unlink: async () => undefined,
      },
    });

    try {
      const callbackUrl = `${server.origin}/oauth/github/callback?state=synthetic-state&code=expired`;
      const expired = await fetch(callbackUrl, { headers, redirect: "manual" });
      expect(expired.status).toBe(401);
      const expiredBody = JSON.stringify(await expired.json());
      expect(expiredBody).toContain("auth_expired");
      expect(expiredBody).not.toContain("synthetic-upstream-marker");

      const malformed = await fetch(callbackUrl, { headers, redirect: "manual" });
      expect(malformed.status).toBe(502);
      expect(await malformed.json()).toMatchObject({ code: "session_interrupted" });
      for (const _ of [1, 2]) {
        const upstream = await fetch(callbackUrl, { headers, redirect: "manual" });
        expect(upstream.status).toBe(502);
        const upstreamBody = JSON.stringify(await upstream.json());
        expect(upstreamBody).toContain("session_interrupted");
        expect(upstreamBody).not.toContain("synthetic outage");
      }
      expect(invalidateActor).not.toHaveBeenCalled();
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

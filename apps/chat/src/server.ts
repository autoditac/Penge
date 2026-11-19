import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { chmodSync, lstatSync, realpathSync } from "node:fs";
import { basename, dirname, isAbsolute, normalize } from "node:path";

import pino, { type Logger } from "pino";
import { z } from "zod/v3";

import type { ChatConfig } from "./config.js";
import {
  AuthenticationError,
  AuthorizationError,
  FeatureDisabledError,
  HydraFusionUnavailableError,
  PengeError,
  ServerStartupError,
  ServiceShuttingDownError,
  SessionLimitError,
  UpstreamResponseError,
} from "./errors.js";
import { bindTrustedIdentity } from "./identity.js";
import type { ChatRuntime } from "./runtime.js";
import type { StreamEvent } from "./stream.js";

const AskRequestSchema = z.object({ question: z.string().trim().min(1).max(8_000) }).strict();
const StopRequestSchema = z.object({ sessionId: z.string().uuid() }).strict();
const MAX_SSE_BUFFER_BYTES = 256 * 1024;
const MAX_SSE_DRAIN_MS = 5_000;
const AuthStatusSchema = z
  .object({
    github: z
      .object({
        state: z.enum(["linked", "not-linked", "expired"]),
        login: z.string().min(1).nullable(),
      })
      .strict(),
    model: z
      .object({
        id: z.literal("hydrafusion"),
        available: z.boolean(),
      })
      .strict(),
    featureEnabled: z.boolean(),
  })
  .strict();

interface ChatServerRuntime {
  start(actorId: string, question: string, sink: (event: StreamEvent) => void): Promise<string>;
  cancel(actorId: string, sessionId: string, reason?: string): Promise<void>;
  disconnect(actorId: string, sessionId: string): Promise<void>;
  cleanupIdle(now?: number): Promise<number>;
  close(): Promise<void>;
  isModelAvailable(actorId: string): boolean;
  ensureModelAvailable(actorId: string): Promise<boolean>;
  invalidateActor(actorId: string): Promise<void>;
}

interface OAuthFlow {
  begin(actorId: string): Promise<string>;
  complete(actorId: string, state: string, code: string): Promise<string>;
  status(
    actorId: string,
  ): Promise<{ state: "linked" | "not-linked" | "expired"; login: string | null }>;
  unlink(actorId: string): Promise<void>;
}

export interface ChatServerDependencies {
  runtime: ChatServerRuntime | ChatRuntime;
  oauth: OAuthFlow;
  logger?: Logger;
}

export interface RunningChatServer {
  origin: string;
  close(): Promise<void>;
}

function validateSocketDirectory(socketPath: string): void {
  if (
    !isAbsolute(socketPath) ||
    normalize(socketPath) !== socketPath ||
    basename(socketPath) !== "chat.sock" ||
    Buffer.byteLength(socketPath) > 100
  ) {
    throw new ServerStartupError("invalid chat socket path");
  }
  const directory = dirname(socketPath);
  const directoryStat = lstatSync(directory);
  const uid = process.getuid?.();
  if (
    uid === undefined ||
    !directoryStat.isDirectory() ||
    directoryStat.uid !== uid ||
    (directoryStat.mode & 0o7777) !== 0o2750 ||
    realpathSync(directory) !== directory
  ) {
    throw new ServerStartupError(
      "chat socket directory must be owned by the service with mode 2750",
    );
  }
  for (let ancestor = dirname(directory); ; ancestor = dirname(ancestor)) {
    const stat = lstatSync(ancestor);
    if (
      !stat.isDirectory() ||
      (stat.uid !== 0 && stat.uid !== uid) ||
      ((stat.mode & 0o022) !== 0 && (stat.mode & 0o1000) === 0)
    ) {
      throw new ServerStartupError("chat socket directory has an unsafe ancestor");
    }
    if (ancestor === "/") break;
  }
  try {
    lstatSync(socketPath);
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return;
    throw error;
  }
  throw new ServerStartupError("chat socket path already exists; operator recovery is required");
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > 48 * 1024) {
      throw new PengeError("chat/request_too_large", "request body exceeds 48 KiB");
    }
    chunks.push(buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
  } catch {
    throw new PengeError("chat/invalid_json", "request body must be valid JSON");
  }
}

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    "x-content-type-options": "nosniff",
  });
  response.end(JSON.stringify(body));
}

function authenticate(request: IncomingMessage, config: ChatConfig): string {
  return bindTrustedIdentity(
    request.headers,
    config.trustedProxyIssuer,
    config.identityPepper,
    config.proxySharedSecret,
  ).actorId;
}

function assertMutationRequest(
  request: IncomingMessage,
  config: ChatConfig,
  requireJson: boolean,
): void {
  if (request.headers.origin !== new URL(config.publicAppOrigin).origin) {
    throw new PengeError("chat/origin_rejected", "request origin is not trusted");
  }
  if (
    requireJson &&
    request.headers["content-type"]?.split(";", 1)[0]?.trim().toLowerCase() !== "application/json"
  ) {
    throw new PengeError("chat/content_type_rejected", "request content type must be JSON");
  }
}

function routeIdentifier(method: string | undefined, pathname: string): string {
  const route = `${method ?? "UNKNOWN"} ${pathname}`;
  return new Set([
    "GET /health",
    "GET /v1/auth/status",
    "GET /oauth/github/start",
    "GET /oauth/github/callback",
    "DELETE /v1/auth/github",
    "POST /v1/chat",
    "POST /v1/chat/stop",
  ]).has(route)
    ? route
    : "unrecognized";
}

function errorStatus(error: unknown): number {
  if (error instanceof AuthenticationError) return 401;
  if (error instanceof AuthorizationError) return 404;
  if (error instanceof SessionLimitError) return 429;
  if (error instanceof ServiceShuttingDownError) return 503;
  if (error instanceof PengeError && error.code === "chat/origin_rejected") return 403;
  if (error instanceof PengeError && error.code === "chat/content_type_rejected") return 415;
  if (error instanceof FeatureDisabledError || error instanceof HydraFusionUnavailableError) {
    return 503;
  }
  if (error instanceof UpstreamResponseError) return 502;
  if (error instanceof z.ZodError) return 400;
  if (error instanceof PengeError) return 400;
  return 500;
}

function publicError(error: unknown): { code: string; message: string } {
  if (error instanceof HydraFusionUnavailableError) {
    return { code: "hydrafusion_unavailable", message: "Copilot Fusion is unavailable." };
  }
  if (error instanceof FeatureDisabledError) {
    return { code: "hydrafusion_unavailable", message: "Ask Penge is not enabled." };
  }
  if (error instanceof AuthenticationError) {
    return { code: "auth_expired", message: "Authentication is required." };
  }
  if (error instanceof SessionLimitError) {
    return { code: "rate_limit", message: "The chat concurrency limit was reached." };
  }
  if (error instanceof ServiceShuttingDownError) {
    return { code: "session_interrupted", message: "The chat service is shutting down." };
  }
  if (error instanceof AuthorizationError) {
    return { code: "not_found", message: "The requested chat session was not found." };
  }
  if (error instanceof UpstreamResponseError) {
    return { code: "session_interrupted", message: "The request could not be completed." };
  }
  if (error instanceof z.ZodError || error instanceof PengeError) {
    return { code: "invalid_request", message: "The request was invalid." };
  }
  return { code: "session_interrupted", message: "The request could not be completed." };
}

export async function startChatServer(
  config: ChatConfig,
  dependencies: ChatServerDependencies,
): Promise<RunningChatServer> {
  const logger =
    dependencies.logger ??
    pino({
      level: "info",
      redact: {
        paths: ["req.headers", "question", "prompt", "token", "accessToken", "refreshToken"],
        censor: "[REDACTED]",
      },
    });
  const backgroundTasks = new Set<Promise<void>>();
  const backgroundErrors: unknown[] = [];
  const requestHandlers = new Set<Promise<void>>();
  let closing = false;
  let closePromise: Promise<void> | undefined;
  const observe = (task: Promise<void>, operation: string): void => {
    const tracked = task
      .catch((error: unknown) => {
        backgroundErrors.push(error);
        logger.error(
          { operation, errorType: error instanceof Error ? error.name : "UnknownError" },
          "chat background operation failed",
        );
      })
      .finally(() => {
        backgroundTasks.delete(tracked);
      });
    backgroundTasks.add(tracked);
  };

  const handleRequest = async (
    request: IncomingMessage,
    response: ServerResponse,
  ): Promise<void> => {
    let url: URL;
    try {
      url = new URL(request.url ?? "/", config.publicApiBase);
    } catch {
      logger.warn(
        { code: "chat/invalid_url", method: request.method, status: 400 },
        "chat request target was invalid",
      );
      sendJson(response, 400, { code: "invalid_request", message: "The request was invalid." });
      return;
    }
    try {
      if (request.method === "GET" && url.pathname === "/health") {
        sendJson(response, 200, {
          status: "ok",
          feature: config.productionEnabled ? "enabled" : "disabled",
          model: config.productionEnabled ? "hydrafusion" : null,
        });
        return;
      }

      const actorId = authenticate(request, config);
      if (request.method === "POST" || request.method === "DELETE") {
        assertMutationRequest(request, config, request.method === "POST");
      }
      if (request.method === "GET" && url.pathname === "/v1/auth/status") {
        const github = await dependencies.oauth.status(actorId);
        if (closing || response.destroyed) return;
        const modelAvailable =
          github.state === "linked"
            ? await dependencies.runtime.ensureModelAvailable(actorId)
            : false;
        sendJson(
          response,
          200,
          AuthStatusSchema.parse({
            github,
            model: {
              id: "hydrafusion",
              available: modelAvailable,
            },
            featureEnabled: config.productionEnabled,
          }),
        );
        return;
      }
      if (request.method === "GET" && url.pathname === "/oauth/github/start") {
        const location = await dependencies.oauth.begin(actorId);
        response.writeHead(302, { location, "cache-control": "no-store" });
        response.end();
        return;
      }
      if (request.method === "DELETE" && url.pathname === "/v1/auth/github") {
        await dependencies.oauth.unlink(actorId);
        await dependencies.runtime.invalidateActor(actorId);
        sendJson(response, 200, { status: "unlinked" });
        return;
      }
      if (request.method === "GET" && url.pathname === "/oauth/github/callback") {
        const state = url.searchParams.get("state");
        const code = url.searchParams.get("code");
        if (state === null || code === null) {
          throw new AuthenticationError("GitHub OAuth callback is missing state or code");
        }
        await dependencies.oauth.complete(actorId, state, code);
        await dependencies.runtime.invalidateActor(actorId);
        const location = new URL("/ask?github=linked", config.publicAppOrigin).toString();
        response.writeHead(302, { location, "cache-control": "no-store" });
        response.end();
        return;
      }
      if (request.method === "POST" && url.pathname === "/v1/chat/stop") {
        const input = StopRequestSchema.parse(await readJson(request));
        await dependencies.runtime.cancel(actorId, input.sessionId);
        sendJson(response, 202, { status: "cancelling" });
        return;
      }
      if (request.method === "POST" && url.pathname === "/v1/chat") {
        const input = AskRequestSchema.parse(await readJson(request));
        if (closing || response.destroyed) return;
        const github = await dependencies.oauth.status(actorId);
        if (closing || response.destroyed) return;
        if (github.state !== "linked") {
          throw new AuthenticationError("linked GitHub identity is required");
        }
        const connection: { sessionId?: string } = {};
        const pending: Array<{ chunk: string; bytes: number; terminal: boolean }> = [];
        let streaming = false;
        let blocked = false;
        let endAfterDrain = false;
        let ended = false;
        let disconnectRequested = false;
        let pendingBytes = 0;
        let drainTimer: NodeJS.Timeout | undefined;
        const disconnect = (): void => {
          if (disconnectRequested || connection.sessionId === undefined) return;
          disconnectRequested = true;
          observe(dependencies.runtime.disconnect(actorId, connection.sessionId), "disconnect");
        };
        const clearDrainTimer = (): void => {
          if (drainTimer !== undefined) {
            clearTimeout(drainTimer);
            drainTimer = undefined;
          }
        };
        const failDelivery = (): void => {
          if (response.destroyed || response.writableFinished) return;
          clearDrainTimer();
          response.destroy();
          disconnect();
        };
        const armDrainTimer = (): void => {
          clearDrainTimer();
          drainTimer = setTimeout(
            failDelivery,
            Math.min(config.httpRequestTimeoutMs, MAX_SSE_DRAIN_MS),
          );
          drainTimer.unref();
        };
        const flush = (): void => {
          if (!streaming || blocked || ended || response.destroyed) return;
          while (pending.length > 0) {
            const event = pending.shift()!;
            pendingBytes -= event.bytes;
            const accepted = response.write(event.chunk);
            if (!accepted) {
              blocked = true;
              endAfterDrain = event.terminal;
              armDrainTimer();
              return;
            }
            if (event.terminal) {
              ended = true;
              armDrainTimer();
              response.end();
              return;
            }
          }
        };
        const sink = (event: StreamEvent): void => {
          if (ended || response.destroyed) return;
          const chunk = `data: ${JSON.stringify(event)}\n\n`;
          const bytes = Buffer.byteLength(chunk);
          if (response.writableLength + pendingBytes + bytes > MAX_SSE_BUFFER_BYTES) {
            failDelivery();
            return;
          }
          pending.push({
            chunk,
            bytes,
            terminal: event.type === "completion" || event.type === "error",
          });
          pendingBytes += bytes;
          flush();
        };
        response.on("drain", () => {
          blocked = false;
          if (endAfterDrain) {
            endAfterDrain = false;
            ended = true;
            response.end();
            return;
          }
          clearDrainTimer();
          flush();
        });
        response.on("finish", clearDrainTimer);
        response.on("close", () => {
          clearDrainTimer();
          if (!response.writableFinished) disconnect();
        });
        connection.sessionId = await dependencies.runtime.start(actorId, input.question, sink);
        if (response.destroyed) {
          await dependencies.runtime.disconnect(actorId, connection.sessionId);
          return;
        }
        response.writeHead(200, {
          "cache-control": "no-store",
          connection: "keep-alive",
          "content-type": "text/event-stream; charset=utf-8",
          "x-accel-buffering": "no",
          "x-content-type-options": "nosniff",
          "x-penge-chat-session-id": connection.sessionId,
        });
        response.flushHeaders();
        streaming = true;
        flush();
        return;
      }

      sendJson(response, 404, { code: "not_found", message: "Route not found." });
    } catch (error) {
      logger.warn(
        {
          code: error instanceof PengeError ? error.code : "chat/unexpected",
          method: request.method,
          route: routeIdentifier(request.method, url.pathname),
          status: errorStatus(error),
        },
        "chat request failed",
      );
      if (response.destroyed) {
        return;
      }
      if (!response.headersSent) {
        sendJson(response, errorStatus(error), publicError(error));
      } else if (!response.destroyed) {
        response.end();
      }
    }
  };
  const server = createServer((request, response) => {
    if (closing) {
      sendJson(response, 503, {
        code: "session_interrupted",
        message: "The chat service is shutting down.",
      });
      return;
    }
    const handler = handleRequest(request, response)
      .catch((error: unknown) => {
        backgroundErrors.push(error);
        logger.error(
          {
            operation: "request_handler",
            errorType: error instanceof Error ? error.name : "UnknownError",
          },
          "chat request handler failed",
        );
        response.destroy();
      })
      .finally(() => {
        requestHandlers.delete(handler);
      });
    requestHandlers.add(handler);
  });
  server.requestTimeout = config.httpRequestTimeoutMs;
  server.headersTimeout = config.httpRequestTimeoutMs;
  server.keepAliveTimeout = Math.min(config.httpRequestTimeoutMs, 5_000);

  if (config.httpSocketPath !== undefined) validateSocketDirectory(config.httpSocketPath);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    const listening = (): void => {
      server.off("error", reject);
      resolve();
    };
    if (config.httpSocketPath !== undefined) server.listen(config.httpSocketPath, listening);
    else server.listen(config.httpPort, config.httpHost, listening);
  });
  const address = server.address();
  if (address === null) {
    throw new ServerStartupError("chat server did not bind a listener");
  }
  if (typeof address === "string") {
    try {
      chmodSync(address, 0o660);
      const socket = lstatSync(address);
      const directory = lstatSync(dirname(address));
      if (!socket.isSocket() || socket.uid !== process.getuid?.() || socket.gid !== directory.gid) {
        throw new ServerStartupError("chat socket ownership does not match the reviewed directory");
      }
    } catch (error) {
      await new Promise<void>((resolve) => server.close(() => resolve()));
      throw error;
    }
  }
  const idleTimer = setInterval(
    () => {
      observe(
        dependencies.runtime.cleanupIdle().then(() => undefined),
        "idle_cleanup",
      );
    },
    Math.min(config.idleTimeoutMs, 30_000),
  );
  idleTimer.unref();
  const origin =
    typeof address === "string"
      ? `http+unix://${encodeURIComponent(address)}`
      : `http://${address.address.includes(":") ? `[${address.address}]` : address.address}:${address.port}`;
  if (typeof address === "string") logger.info({ transport: "unix" }, "chat server listening");
  else logger.info({ host: address.address, port: address.port }, "chat server listening");

  return {
    origin,
    close: () => {
      if (closePromise !== undefined) return closePromise;
      closing = true;
      clearInterval(idleTimer);
      closePromise = (async () => {
        const failures: unknown[] = [];
        try {
          await new Promise<void>((resolve, reject) => {
            server.close((error) => (error === undefined ? resolve() : reject(error)));
            server.closeAllConnections();
          });
        } catch (error) {
          failures.push(error);
        }
        while (requestHandlers.size > 0) {
          await Promise.all([...requestHandlers]);
        }
        try {
          await dependencies.runtime.close();
        } catch (error) {
          failures.push(error);
        }
        while (backgroundTasks.size > 0) {
          await Promise.all([...backgroundTasks]);
        }
        failures.push(...backgroundErrors);
        if (failures.length > 0) {
          throw new AggregateError(failures, "chat server cleanup failed");
        }
      })();
      return closePromise;
    },
  };
}

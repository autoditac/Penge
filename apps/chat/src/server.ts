import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

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
  SessionLimitError,
} from "./errors.js";
import { bindTrustedIdentity } from "./identity.js";
import type { ChatRuntime } from "./runtime.js";
import type { StreamEvent } from "./stream.js";

const AskRequestSchema = z.object({ question: z.string().trim().min(1).max(8_000) }).strict();
const StopRequestSchema = z.object({ sessionId: z.string().uuid() }).strict();
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

const MAX_SSE_BUFFER_BYTES = 1_024 * 1_024;

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
  if (error instanceof PengeError && error.code === "chat/origin_rejected") return 403;
  if (error instanceof PengeError && error.code === "chat/content_type_rejected") return 415;
  if (error instanceof FeatureDisabledError || error instanceof HydraFusionUnavailableError) {
    return 503;
  }
  if (error instanceof z.ZodError) return 400;
  if (error instanceof PengeError) return 400;
  return 500;
}

function publicError(error: unknown): { code: string; message: string } {
  if (error instanceof HydraFusionUnavailableError) {
    return { code: "hydrafusion_unavailable", message: "HydraFusion is unavailable." };
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
  if (error instanceof AuthorizationError) {
    return { code: "not_found", message: "The requested chat session was not found." };
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

  const server = createServer(async (request, response) => {
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
        const github = await dependencies.oauth.status(actorId);
        if (github.state !== "linked") {
          throw new AuthenticationError("linked GitHub identity is required");
        }
        const connection: { sessionId?: string } = {};
        const pending: StreamEvent[] = [];
        let pendingBytes = 0;
        const outbound: Array<{ payload: string; terminal: boolean; bytes: number }> = [];
        let outboundBytes = 0;
        let deliveryTimer: NodeJS.Timeout | undefined;
        let streaming = false;
        let ended = false;
        let disconnectObserved = false;
        let terminalPending = false;
        const disconnect = (): void => {
          if (disconnectObserved || connection.sessionId === undefined) return;
          disconnectObserved = true;
          observe(dependencies.runtime.disconnect(actorId, connection.sessionId), "disconnect");
        };
        const failDelivery = (): void => {
          if (ended) return;
          ended = true;
          if (deliveryTimer !== undefined) clearTimeout(deliveryTimer);
          response.destroy();
          disconnect();
        };
        const armDeliveryDeadline = (): void => {
          if (deliveryTimer !== undefined) return;
          deliveryTimer = setTimeout(failDelivery, config.httpRequestTimeoutMs);
          deliveryTimer.unref();
        };
        const flushOutbound = (): void => {
          while (outbound.length > 0 && !response.destroyed) {
            const item = outbound.shift();
            if (item === undefined) return;
            outboundBytes -= item.bytes;
            const writable = response.write(item.payload);
            if (!writable) {
              if (item.terminal) terminalPending = true;
              armDeliveryDeadline();
              return;
            }
            if (item.terminal) {
              ended = true;
              response.end();
              return;
            }
          }
          if (terminalPending && !response.destroyed) {
            terminalPending = false;
            ended = true;
            response.end();
          } else if (outbound.length === 0 && deliveryTimer !== undefined) {
            clearTimeout(deliveryTimer);
            deliveryTimer = undefined;
          }
        };
        const enqueue = (event: StreamEvent): void => {
          const payload = `data: ${JSON.stringify(event)}\n\n`;
          const bytes = Buffer.byteLength(payload);
          if (
            bytes > MAX_SSE_BUFFER_BYTES ||
            outboundBytes + response.writableLength + bytes > MAX_SSE_BUFFER_BYTES
          ) {
            failDelivery();
            return;
          }
          outbound.push({
            payload,
            terminal: event.type === "completion" || event.type === "error",
            bytes,
          });
          outboundBytes += bytes;
          flushOutbound();
        };
        const sink = (event: StreamEvent): void => {
          if (ended || response.destroyed) return;
          if (!streaming) {
            const bytes = Buffer.byteLength(JSON.stringify(event));
            if (pendingBytes + bytes > MAX_SSE_BUFFER_BYTES) {
              failDelivery();
              return;
            }
            pending.push(event);
            pendingBytes += bytes;
            return;
          }
          enqueue(event);
        };
        response.on("close", () => {
          if (deliveryTimer !== undefined) clearTimeout(deliveryTimer);
          if (!ended) disconnect();
        });
        response.on("drain", flushOutbound);
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
        for (const event of pending) {
          sink(event);
        }
        pending.length = 0;
        pendingBytes = 0;
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
      if (!response.headersSent) {
        sendJson(response, errorStatus(error), publicError(error));
      } else if (!response.destroyed) {
        response.end();
      }
    }
  });
  server.requestTimeout = config.httpRequestTimeoutMs;
  server.headersTimeout = config.httpRequestTimeoutMs;
  server.keepAliveTimeout = Math.min(config.httpRequestTimeoutMs, 5_000);

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(config.httpPort, config.httpHost, () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new ServerStartupError("chat server did not bind a TCP loopback address");
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
  logger.info({ host: address.address, port: address.port }, "chat server listening");

  return {
    origin: `http://${address.address.includes(":") ? `[${address.address}]` : address.address}:${address.port}`,
    close: async () => {
      clearInterval(idleTimer);
      const failures: unknown[] = [];
      try {
        await new Promise<void>((resolve, reject) => {
          server.close((error) => (error === undefined ? resolve() : reject(error)));
          server.closeAllConnections();
        });
      } catch (error) {
        failures.push(error);
      }
      try {
        await dependencies.runtime.close();
      } catch (error) {
        failures.push(error);
      }
      await Promise.all([...backgroundTasks]);
      failures.push(...backgroundErrors);
      if (failures.length > 0) {
        throw new AggregateError(failures, "chat server cleanup failed");
      }
    },
  };
}

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

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > 16_384) {
      throw new PengeError("chat/request_too_large", "request body exceeds 16 KiB");
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

function errorStatus(error: unknown): number {
  if (error instanceof AuthenticationError) return 401;
  if (error instanceof AuthorizationError) return 404;
  if (error instanceof SessionLimitError) return 429;
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
    const url = new URL(request.url ?? "/", config.publicApiBase);
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
      if (request.method === "GET" && url.pathname === "/v1/auth/status") {
        const github = await dependencies.oauth.status(actorId);
        sendJson(
          response,
          200,
          AuthStatusSchema.parse({
            github,
            model: {
              id: "hydrafusion",
              available:
                github.state === "linked" && dependencies.runtime.isModelAvailable(actorId),
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
        let streaming = false;
        let ended = false;
        const sink = (event: StreamEvent): void => {
          if (ended || response.destroyed) return;
          if (!streaming) {
            pending.push(event);
            return;
          }
          response.write(`data: ${JSON.stringify(event)}\n\n`);
          if (event.type === "completion" || event.type === "error") {
            ended = true;
            response.end();
          }
        };
        response.on("close", () => {
          if (!ended && connection.sessionId !== undefined) {
            observe(dependencies.runtime.disconnect(actorId, connection.sessionId), "disconnect");
          }
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
        streaming = true;
        for (const event of pending) {
          sink(event);
        }
        return;
      }

      sendJson(response, 404, { code: "not_found", message: "Route not found." });
    } catch (error) {
      logger.warn(
        {
          code: error instanceof PengeError ? error.code : "chat/unexpected",
          method: request.method,
          path: url.pathname,
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
        await dependencies.runtime.close();
      } catch (error) {
        failures.push(error);
      }
      await Promise.all([...backgroundTasks]);
      failures.push(...backgroundErrors);
      try {
        await new Promise<void>((resolve, reject) => {
          server.close((error) => (error === undefined ? resolve() : reject(error)));
          server.closeAllConnections();
        });
      } catch (error) {
        failures.push(error);
      }
      if (failures.length > 0) {
        throw new AggregateError(failures, "chat server cleanup failed");
      }
    },
  };
}

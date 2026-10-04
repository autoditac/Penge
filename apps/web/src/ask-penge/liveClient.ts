import { z } from "zod";

import { ASK_STREAM_PROTOCOL_VERSION, askRequestSchema, askStreamEventSchema } from "./contract";
import type {
  AskRequest,
  AskStreamErrorEvent,
  AskTransport,
  AskTransportSession,
} from "./contract";

const githubAuthStatusSchema = z.discriminatedUnion("state", [
  z.object({ state: z.literal("linked"), login: z.string().min(1) }).strict(),
  z.object({ state: z.literal("not-linked"), login: z.null() }).strict(),
  z
    .object({
      state: z.literal("expired"),
      login: z.string().min(1).nullable(),
    })
    .strict(),
]);

export const askAuthStatusSchema = z
  .object({
    github: githubAuthStatusSchema,
    model: z
      .object({
        id: z.literal("hydrafusion"),
        available: z.boolean(),
      })
      .strict(),
    featureEnabled: z.boolean(),
  })
  .strict();

export type AskAuthStatus = z.infer<typeof askAuthStatusSchema>;
export type FetchLike = typeof fetch;

export class AskChatClientError extends Error {
  readonly code: string;
  readonly status: number | null;

  constructor(code: string, message: string, status: number | null = null) {
    super(message);
    this.name = "AskChatClientError";
    this.code = code;
    this.status = status;
  }
}

export type AskChatClient = {
  readonly getStatus: () => Promise<AskAuthStatus>;
  readonly githubStartUrl: string;
  readonly unlinkGitHub: () => Promise<void>;
  readonly transport: AskTransport;
};

export function createAskChatClient(
  configuredBaseUrl: string,
  fetchFn: FetchLike = fetch,
  currentLocation = window.location.href,
): AskChatClient {
  const baseUrl = resolveSameOriginBaseUrl(configuredBaseUrl, currentLocation);

  return {
    getStatus: async () => {
      const response = await fetchFn(endpoint(baseUrl, "v1/auth/status"), {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw httpError("auth_status_failed", "Could not load Ask Penge account status.", response);
      }
      return askAuthStatusSchema.parse(await response.json());
    },
    githubStartUrl: endpoint(baseUrl, "oauth/github/start").toString(),
    unlinkGitHub: async () => {
      const response = await fetchFn(endpoint(baseUrl, "v1/auth/github"), {
        method: "DELETE",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw httpError("github_unlink_failed", "Could not unlink the GitHub account.", response);
      }
    },
    transport: createFetchAskTransport(baseUrl, fetchFn),
  };
}

export function resolveSameOriginBaseUrl(configuredBaseUrl: string, currentLocation: string): URL {
  const value = configuredBaseUrl.trim();
  if (!value) {
    throw new AskChatClientError("chat_base_url_empty", "Ask Penge chat URL is empty.");
  }

  const locationUrl = new URL(currentLocation);
  const resolved = new URL(value, locationUrl);
  if (resolved.origin !== locationUrl.origin) {
    throw new AskChatClientError(
      "chat_base_url_cross_origin",
      "Ask Penge chat URL must use the current application origin.",
    );
  }

  resolved.pathname = `${resolved.pathname.replace(/\/+$/, "")}/`;
  resolved.search = "";
  resolved.hash = "";
  return resolved;
}

export class SseDataParser {
  private lineBuffer = "";
  private dataLines: string[] = [];

  push(chunk: string): string[] {
    this.lineBuffer += chunk;
    const payloads: string[] = [];

    while (this.lineBuffer.length > 0) {
      const lineBreak = findLineBreak(this.lineBuffer);
      if (lineBreak === null) {
        break;
      }
      const line = this.lineBuffer.slice(0, lineBreak.index);
      this.lineBuffer = this.lineBuffer.slice(lineBreak.index + lineBreak.length);
      this.processLine(line, payloads);
    }

    return payloads;
  }

  finish(): string[] {
    const payloads: string[] = [];
    if (this.lineBuffer.length > 0) {
      this.processLine(this.lineBuffer.replace(/\r$/, ""), payloads);
      this.lineBuffer = "";
    }
    this.dispatch(payloads);
    return payloads;
  }

  private processLine(line: string, payloads: string[]): void {
    if (line === "") {
      this.dispatch(payloads);
      return;
    }
    if (line.startsWith(":")) {
      return;
    }

    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    if (field !== "data") {
      return;
    }
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }
    this.dataLines.push(value);
  }

  private dispatch(payloads: string[]): void {
    if (this.dataLines.length === 0) {
      return;
    }
    payloads.push(this.dataLines.join("\n"));
    this.dataLines = [];
  }
}

function createFetchAskTransport(baseUrl: URL, fetchFn: FetchLike): AskTransport {
  return {
    start(candidate: AskRequest): AskTransportSession {
      const request = askRequestSchema.parse(candidate);
      const controller = new AbortController();
      const listeners = new Set<(event: unknown) => void>();
      let started = false;
      let closed = false;
      let userStopped = false;
      let sessionId: string | null = null;
      let nextSequence = 0;
      let terminal = false;

      const emit = (event: unknown): void => {
        for (const listener of listeners) {
          listener(event);
        }
      };

      const emitClientError = (
        code: AskStreamErrorEvent["code"],
        message: string,
        retryable: boolean,
      ): void => {
        if (terminal || closed) {
          return;
        }
        terminal = true;
        emit({
          version: ASK_STREAM_PROTOCOL_VERSION,
          sessionId: sessionId ?? createClientSessionId(),
          id: `client-error-${nextSequence}`,
          sequence: nextSequence,
          type: "error",
          code,
          message,
          retryable,
        } satisfies AskStreamErrorEvent);
      };

      const close = (): void => {
        if (closed) {
          return;
        }
        closed = true;
        controller.abort();
      };

      const processPayload = (payload: string): boolean => {
        let candidateEvent: unknown;
        try {
          candidateEvent = JSON.parse(payload);
        } catch {
          emit({ malformedSseData: payload });
          close();
          return false;
        }

        const parsed = askStreamEventSchema.safeParse(candidateEvent);
        emit(candidateEvent);
        if (!parsed.success) {
          close();
          return false;
        }

        sessionId = parsed.data.sessionId;
        nextSequence = parsed.data.sequence + 1;
        terminal = parsed.data.type === "completion" || parsed.data.type === "error";
        return true;
      };

      const start = async (): Promise<void> => {
        try {
          const response = await fetchFn(endpoint(baseUrl, "v1/chat"), {
            method: "POST",
            credentials: "same-origin",
            headers: {
              Accept: "text/event-stream",
              "Content-Type": "application/json",
            },
            body: JSON.stringify(request),
            signal: controller.signal,
          });
          if (!response.ok) {
            const mapped = await mapChatHttpError(response);
            emitClientError(mapped.code, mapped.message, mapped.retryable);
            return;
          }
          if (response.body === null) {
            emitClientError(
              "session_interrupted",
              "The Ask Penge response stream was unavailable.",
              true,
            );
            return;
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          const parser = new SseDataParser();
          while (!closed) {
            const result = await reader.read();
            const payloads = result.done
              ? parser.finish()
              : parser.push(decoder.decode(result.value, { stream: true }));
            for (const payload of payloads) {
              if (!processPayload(payload)) {
                return;
              }
            }
            if (result.done) {
              break;
            }
          }

          if (!terminal && !closed) {
            emitClientError(
              "session_interrupted",
              "The Ask Penge connection ended before the answer completed.",
              true,
            );
          }
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") {
            return;
          }
          if (!userStopped && !closed) {
            emitClientError(
              "session_interrupted",
              "The Ask Penge connection was interrupted. Reconnect to try again.",
              true,
            );
          }
        }
      };

      return {
        stop: async () => {
          userStopped = true;
          if (sessionId !== null) {
            const response = await fetchFn(endpoint(baseUrl, "v1/chat/stop"), {
              method: "POST",
              credentials: "same-origin",
              headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ sessionId }),
            });
            if (!response.ok) {
              throw httpError(
                "chat_stop_failed",
                "The server did not confirm Ask Penge cancellation.",
                response,
              );
            }
          }
          close();
        },
        close,
        subscribe: (callback) => {
          listeners.add(callback);
          if (!started) {
            started = true;
            void start();
          }
          return () => {
            listeners.delete(callback);
          };
        },
      };
    },
  };
}

function endpoint(baseUrl: URL, path: string): URL {
  return new URL(path.replace(/^\/+/, ""), baseUrl);
}

function httpError(code: string, message: string, response: Response): AskChatClientError {
  return new AskChatClientError(code, message, response.status);
}

const publicChatErrorSchema = z
  .object({
    code: z.enum([
      "auth_expired",
      "hydrafusion_unavailable",
      "rate_limit",
      "session_interrupted",
      "data_missing",
      "missing_fx",
      "tool_timeout",
    ]),
  })
  .passthrough();

async function mapChatHttpError(response: Response): Promise<{
  code: AskStreamErrorEvent["code"];
  message: string;
  retryable: boolean;
}> {
  const publicCode = await readPublicErrorCode(response);
  if (publicCode === "hydrafusion_unavailable") {
    return {
      code: publicCode,
      message: "Exact HydraFusion is unavailable for the linked GitHub account.",
      retryable: false,
    };
  }
  if (publicCode === "auth_expired") {
    return {
      code: "auth_expired",
      message: "The linked GitHub authorization expired. Reauthenticate to continue.",
      retryable: false,
    };
  }
  if (publicCode === "rate_limit") {
    return {
      code: publicCode,
      message: "The Copilot rate limit was reached. Retry after the service recovers.",
      retryable: true,
    };
  }
  if (publicCode === "tool_timeout") {
    return {
      code: publicCode,
      message: "The evidence lookup timed out before the answer completed.",
      retryable: true,
    };
  }
  if (
    publicCode === "data_missing" ||
    publicCode === "missing_fx" ||
    publicCode === "session_interrupted"
  ) {
    return {
      code: publicCode,
      message: "The Ask Penge service could not start this answer.",
      retryable: true,
    };
  }
  if (response.status === 401 || response.status === 403) {
    return {
      code: "auth_expired",
      message: "The linked GitHub authorization could not be verified. Reauthenticate to continue.",
      retryable: false,
    };
  }
  if (response.status === 429) {
    return {
      code: "rate_limit",
      message: "The Copilot rate limit was reached. Retry after the service recovers.",
      retryable: true,
    };
  }
  if (response.status === 504) {
    return {
      code: "tool_timeout",
      message: "The evidence lookup timed out before the answer completed.",
      retryable: true,
    };
  }
  return {
    code: "session_interrupted",
    message: "The Ask Penge service could not start this answer.",
    retryable: true,
  };
}

async function readPublicErrorCode(
  response: Response,
): Promise<AskStreamErrorEvent["code"] | null> {
  try {
    const body = await response.text();
    if (body.length === 0 || body.length > 4_096) {
      return null;
    }
    const parsed = publicChatErrorSchema.safeParse(JSON.parse(body));
    return parsed.success ? parsed.data.code : null;
  } catch {
    return null;
  }
}

function createClientSessionId(): string {
  return `client-${globalThis.crypto?.randomUUID?.() ?? Date.now().toString(36)}`;
}

function findLineBreak(value: string): { index: number; length: number } | null {
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (character === "\n") {
      return { index, length: 1 };
    }
    if (character === "\r") {
      if (index === value.length - 1) {
        return null;
      }
      return { index, length: value[index + 1] === "\n" ? 2 : 1 };
    }
  }
  return null;
}

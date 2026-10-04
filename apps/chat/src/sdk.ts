import { mkdir, rm } from "node:fs/promises";
import { join } from "node:path";

import {
  CopilotClient,
  ToolSet,
  type CopilotClientOptions,
  type GitHubTokenProvider,
  type SessionConfig,
  type SessionEvent,
} from "@github/copilot-sdk";
import { z } from "zod/v3";

import { HYDRAFUSION_MODEL, MCP_CHAT_TOOL_ALLOWLIST, type ChatConfig } from "./config.js";
import {
  CopilotRuntimeError,
  FeatureDisabledError,
  HydraFusionUnavailableError,
} from "./errors.js";
import { buildMcpServerConfig } from "./mcp.js";

export interface CopilotEventSink {
  onEvent(event: SessionEvent): void;
}

export interface ActiveCopilotRun {
  send(question: string): Promise<void>;
  abort(): Promise<void>;
  close(): Promise<void>;
}

export interface CopilotRuntime {
  createRun(options: {
    actorId: string;
    sessionId: string;
    tokenProvider: GitHubTokenProvider;
    sink: CopilotEventSink;
  }): Promise<ActiveCopilotRun>;
}

interface CopilotSessionLike {
  send(options: { prompt: string }): Promise<unknown>;
  abort(): Promise<void>;
  disconnect(): Promise<void>;
  on(handler: (event: SessionEvent) => void): () => void;
}

interface CopilotClientLike {
  start(): Promise<void>;
  createSession(config: SessionConfig): Promise<CopilotSessionLike>;
  stop(): Promise<Error[]>;
  forceStop(): Promise<void>;
}

export type CopilotClientFactory = (options: CopilotClientOptions) => CopilotClientLike;

function safeRuntimeEnvironment(): Record<string, string | undefined> {
  return {
    PATH: process.env.PATH,
    TMPDIR: process.env.TMPDIR,
    XDG_RUNTIME_DIR: process.env.XDG_RUNTIME_DIR,
    LANG: process.env.LANG,
  };
}

export function buildSessionConfig(
  config: ChatConfig,
  sessionId: string,
  tokenProvider: GitHubTokenProvider,
): SessionConfig {
  const availableTools = new ToolSet();
  for (const tool of MCP_CHAT_TOOL_ALLOWLIST) {
    availableTools.addMcp(`penge-${tool}`);
  }
  return {
    sessionId,
    model: HYDRAFUSION_MODEL,
    allowedModels: [HYDRAFUSION_MODEL],
    streaming: true,
    enableSessionStore: false,
    enableConfigDiscovery: false,
    includedBuiltinSkills: [],
    requestCanvasRenderer: false,
    requestExtensions: false,
    mcpOAuthTokenStorage: "in-memory",
    gitHubTokenProvider: tokenProvider,
    availableTools,
    excludedTools: new ToolSet().addBuiltIn("*").addCustom("*"),
    onPermissionRequest: () => ({
      kind: "reject",
      feedback: "Penge chat denies every ambient permission request",
    }),
    mcpServers: {
      penge: buildMcpServerConfig(config),
    },
  };
}

async function stopClient(client: CopilotClientLike): Promise<void> {
  const errors = await client.stop();
  if (errors.length > 0) {
    throw new CopilotRuntimeError(
      "chat/copilot_cleanup",
      `Copilot runtime cleanup failed with ${errors.length} error(s)`,
    );
  }
}

async function withTimeout<T>(operation: Promise<T>, timeoutMs: number): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () =>
        reject(
          new CopilotRuntimeError(
            "chat/copilot_timeout",
            `Copilot runtime setup exceeded ${timeoutMs} ms`,
          ),
        ),
      timeoutMs,
    );
    timer.unref();
  });
  try {
    return await Promise.race([operation, timeout]);
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}

const SdkFailureSchema = z
  .object({
    code: z.string().optional(),
    message: z.string().optional(),
  })
  .passthrough();

const MODEL_FAILURE_CODES = new Set([
  "model_not_found",
  "model_not_supported",
  "model_unavailable",
  "model_access_denied",
  "model_not_entitled",
]);

function classifySessionCreationError(error: unknown): unknown {
  const parsed = SdkFailureSchema.safeParse(error);
  if (!parsed.success) {
    return error;
  }
  const code = parsed.data.code?.toLowerCase();
  const message = parsed.data.message ?? "";
  if (
    (code !== undefined && MODEL_FAILURE_CODES.has(code)) ||
    (/hydrafusion/i.test(message) &&
      /\b(?:unavailable|unsupported|not found|not entitled|access denied)\b/i.test(message))
  ) {
    return new HydraFusionUnavailableError(
      `linked GitHub identity cannot create an exact ${HYDRAFUSION_MODEL} session`,
    );
  }
  return error;
}

export class GitHubCopilotRuntime implements CopilotRuntime {
  constructor(
    private readonly config: ChatConfig,
    private readonly createClient: CopilotClientFactory = (options) => new CopilotClient(options),
  ) {}

  async createRun(options: {
    actorId: string;
    sessionId: string;
    tokenProvider: GitHubTokenProvider;
    sink: CopilotEventSink;
  }): Promise<ActiveCopilotRun> {
    if (!this.config.productionEnabled) {
      throw new FeatureDisabledError(
        "Ask Penge is disabled until production is explicitly enabled",
      );
    }

    const baseDirectory = join(
      this.config.copilotBaseDirectory,
      options.actorId,
      options.sessionId,
    );
    await mkdir(baseDirectory, { recursive: true, mode: 0o700 });
    const client = this.createClient({
      mode: "empty",
      baseDirectory,
      workingDirectory: this.config.mcpWorkingDirectory,
      useLoggedInUser: false,
      logLevel: "error",
      env: safeRuntimeEnvironment(),
    });

    let session: CopilotSessionLike | undefined;
    let unsubscribe: (() => void) | undefined;
    let closed = false;
    try {
      await withTimeout(client.start(), this.config.requestTimeoutMs);
      try {
        session = await withTimeout(
          client.createSession(
            buildSessionConfig(this.config, options.sessionId, options.tokenProvider),
          ),
          this.config.requestTimeoutMs,
        );
      } catch (error) {
        throw classifySessionCreationError(error);
      }
      unsubscribe = session.on((event) => options.sink.onEvent(event));
    } catch (error) {
      try {
        await withTimeout(client.forceStop(), this.config.requestTimeoutMs);
      } finally {
        await rm(baseDirectory, { recursive: true, force: true });
      }
      throw error;
    }

    const currentSession = session;
    return {
      send: async (question) => {
        await withTimeout(currentSession.send({ prompt: question }), this.config.requestTimeoutMs);
      },
      abort: async () => {
        await withTimeout(currentSession.abort(), this.config.requestTimeoutMs);
      },
      close: async () => {
        if (closed) {
          return;
        }
        closed = true;
        unsubscribe?.();
        const cleanupErrors: Error[] = [];
        try {
          try {
            await withTimeout(currentSession.disconnect(), this.config.requestTimeoutMs);
          } catch (error) {
            cleanupErrors.push(
              error instanceof Error
                ? error
                : new CopilotRuntimeError("chat/copilot_cleanup", "session disconnect failed"),
            );
          }
          try {
            await withTimeout(stopClient(client), this.config.requestTimeoutMs);
          } catch (error) {
            cleanupErrors.push(
              error instanceof Error
                ? error
                : new CopilotRuntimeError("chat/copilot_cleanup", "client cleanup failed"),
            );
            try {
              await withTimeout(client.forceStop(), this.config.requestTimeoutMs);
            } catch (forceStopError) {
              cleanupErrors.push(
                forceStopError instanceof Error
                  ? forceStopError
                  : new CopilotRuntimeError("chat/copilot_cleanup", "client force cleanup failed"),
              );
            }
          }
        } finally {
          await rm(baseDirectory, { recursive: true, force: true });
        }
        if (cleanupErrors.length > 0) {
          throw new CopilotRuntimeError(
            "chat/copilot_cleanup",
            `Copilot cleanup failed with ${cleanupErrors.length} error(s)`,
          );
        }
      },
    };
  }
}

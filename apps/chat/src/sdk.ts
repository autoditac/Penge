import { mkdir, rm } from "node:fs/promises";
import { join } from "node:path";

import {
  CopilotClient,
  ToolSet,
  type CopilotSession,
  type GitHubTokenProvider,
  type SessionConfig,
  type SessionEvent,
} from "@github/copilot-sdk";

import { HYDRAFUSION_MODEL, MCP_TOOL_ALLOWLIST, type ChatConfig } from "./config.js";
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

function safeRuntimeEnvironment(): Record<string, string | undefined> {
  return {
    PATH: process.env.PATH,
    TMPDIR: process.env.TMPDIR,
    XDG_RUNTIME_DIR: process.env.XDG_RUNTIME_DIR,
    LANG: process.env.LANG,
  };
}

export function assertHydraFusionAvailable(models: readonly { id: string }[]): void {
  if (!models.some((model) => model.id === HYDRAFUSION_MODEL)) {
    throw new HydraFusionUnavailableError(
      `linked GitHub identity is not entitled to ${HYDRAFUSION_MODEL}`,
    );
  }
}

export function buildSessionConfig(
  config: ChatConfig,
  sessionId: string,
  tokenProvider: GitHubTokenProvider,
): SessionConfig {
  const availableTools = new ToolSet();
  for (const tool of MCP_TOOL_ALLOWLIST) {
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

async function stopClient(client: CopilotClient): Promise<void> {
  const errors = await client.stop();
  if (errors.length > 0) {
    await client.forceStop();
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

export class GitHubCopilotRuntime implements CopilotRuntime {
  constructor(private readonly config: ChatConfig) {}

  async createRun(options: {
    actorId: string;
    sessionId: string;
    tokenProvider: GitHubTokenProvider;
    sink: CopilotEventSink;
  }): Promise<ActiveCopilotRun> {
    if (!this.config.productionEnabled || !this.config.entitlementVerified) {
      throw new FeatureDisabledError(
        "Ask Penge is disabled until the linked user passes the HydraFusion entitlement gate",
      );
    }

    const baseDirectory = join(
      this.config.copilotBaseDirectory,
      options.actorId,
      options.sessionId,
    );
    await mkdir(baseDirectory, { recursive: true, mode: 0o700 });
    const client = new CopilotClient({
      mode: "empty",
      baseDirectory,
      workingDirectory: this.config.mcpWorkingDirectory,
      useLoggedInUser: false,
      logLevel: "error",
      env: safeRuntimeEnvironment(),
    });

    let session: CopilotSession | undefined;
    let unsubscribe: (() => void) | undefined;
    let closed = false;
    try {
      await withTimeout(client.start(), this.config.requestTimeoutMs);
      const models = await withTimeout(client.listModels(), this.config.requestTimeoutMs);
      assertHydraFusionAvailable(models);
      session = await withTimeout(
        client.createSession(
          buildSessionConfig(this.config, options.sessionId, options.tokenProvider),
        ),
        this.config.requestTimeoutMs,
      );
      unsubscribe = session.on((event) => options.sink.onEvent(event));
    } catch (error) {
      try {
        await client.forceStop();
      } finally {
        await rm(baseDirectory, { recursive: true, force: true });
      }
      throw error;
    }

    const currentSession = session;
    return {
      send: async (question) => {
        await currentSession.send({ prompt: question });
      },
      abort: async () => {
        await currentSession.abort();
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
            await currentSession.disconnect();
          } catch (error) {
            cleanupErrors.push(
              error instanceof Error
                ? error
                : new CopilotRuntimeError("chat/copilot_cleanup", "session disconnect failed"),
            );
          }
          try {
            await stopClient(client);
          } catch (error) {
            cleanupErrors.push(
              error instanceof Error
                ? error
                : new CopilotRuntimeError("chat/copilot_cleanup", "client cleanup failed"),
            );
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

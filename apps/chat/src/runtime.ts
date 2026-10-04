import { randomUUID } from "node:crypto";

import type { GitHubTokenProvider, SessionEvent } from "@github/copilot-sdk";

import type { ChatConfig } from "./config.js";
import { AuthorizationError, SessionLimitError } from "./errors.js";
import { assertMcpToolAllowed } from "./mcp.js";
import type { ActiveCopilotRun, CopilotRuntime } from "./sdk.js";
import { assertPromptIsSafe, redactedArgumentKeys } from "./security.js";
import { createEventFactory, type StreamEvent, type StreamEventInput } from "./stream.js";
import type { ChatStore } from "./store.js";

export type StreamSink = (event: StreamEvent) => void;

interface TokenProviderFactory {
  providerFor(actorId: string): GitHubTokenProvider;
}

interface ActiveSession {
  actorId: string;
  sessionId: string;
  startedAt: number;
  touchedAt: number;
  run: ActiveCopilotRun;
  emit: (event: StreamEventInput) => StreamEvent;
  sink: StreamSink;
  timeout: NodeJS.Timeout;
  terminal: boolean;
  toolsByCallId: Map<string, string>;
}

function publicErrorMessage(): string {
  return "The chat session was interrupted without retaining its transcript.";
}

export class ChatRuntime {
  private readonly sessions = new Map<string, ActiveSession>();
  private startingCount = 0;

  constructor(
    private readonly config: ChatConfig,
    private readonly copilot: CopilotRuntime,
    private readonly tokenService: TokenProviderFactory,
    private readonly store: ChatStore,
  ) {}

  get activeSessionCount(): number {
    return this.sessions.size;
  }

  hasSessionContent(_sessionId: string): false {
    return false;
  }

  async start(actorId: string, question: string, sink: StreamSink): Promise<string> {
    assertPromptIsSafe(question);
    if (this.sessions.size + this.startingCount >= this.config.maxConcurrentSessions) {
      throw new SessionLimitError("chat concurrency limit reached");
    }
    this.startingCount += 1;
    const sessionId = randomUUID();
    const emit = createEventFactory(sessionId, randomUUID);
    const startedAt = Date.now();
    let run: ActiveCopilotRun;
    try {
      run = await this.copilot.createRun({
        actorId,
        sessionId,
        tokenProvider: this.tokenService.providerFor(actorId),
        sink: {
          onEvent: (event) => {
            void this.handleSdkEvent(sessionId, event);
          },
        },
      });
    } finally {
      this.startingCount -= 1;
    }
    const timeout = setTimeout(() => {
      void this.terminate(sessionId, "timeout", true);
    }, this.config.requestTimeoutMs);
    timeout.unref();
    this.sessions.set(sessionId, {
      actorId,
      sessionId,
      startedAt,
      touchedAt: startedAt,
      run,
      emit,
      sink,
      timeout,
      terminal: false,
      toolsByCallId: new Map(),
    });
    try {
      await this.store.appendAudit({
        actorId,
        sessionId,
        tool: null,
        status: "started",
        durationMs: null,
        argumentKeys: [],
      });
      await run.send(question);
      return sessionId;
    } catch (error) {
      await this.terminate(sessionId, "error", false);
      throw error;
    }
  }

  async cancel(actorId: string, sessionId: string, reason = "user requested stop"): Promise<void> {
    const session = this.ownedSession(actorId, sessionId);
    if (session.terminal) {
      return;
    }
    try {
      await session.run.abort();
    } finally {
      session.sink(
        session.emit({
          type: "completion",
          summary: reason,
          coverage: "partial",
          freshness: "fresh",
          finishReason: "cancelled",
        }),
      );
      await this.terminate(sessionId, "cancelled", false);
    }
  }

  async disconnect(actorId: string, sessionId: string): Promise<void> {
    const session = this.ownedSession(actorId, sessionId);
    try {
      if (!session.terminal) {
        await session.run.abort();
      }
    } finally {
      await this.terminate(sessionId, "cancelled", false);
    }
  }

  async cleanupIdle(now = Date.now()): Promise<number> {
    const idle = [...this.sessions.values()].filter(
      (session) => now - session.touchedAt >= this.config.idleTimeoutMs,
    );
    await Promise.all(idle.map((session) => this.terminate(session.sessionId, "timeout", true)));
    return idle.length;
  }

  async close(): Promise<void> {
    await Promise.all(
      [...this.sessions.values()].map((session) =>
        this.terminate(session.sessionId, "cancelled", false),
      ),
    );
  }

  private ownedSession(actorId: string, sessionId: string): ActiveSession {
    const session = this.sessions.get(sessionId);
    if (session === undefined || session.actorId !== actorId) {
      throw new AuthorizationError("chat session does not belong to the authenticated actor");
    }
    return session;
  }

  private async handleSdkEvent(sessionId: string, event: SessionEvent): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (session === undefined || session.terminal) {
      return;
    }
    session.touchedAt = Date.now();
    switch (event.type) {
      case "assistant.message_delta":
        if (event.agentId === undefined && event.data.deltaContent.length > 0) {
          session.sink(
            session.emit({
              type: "text",
              stream: "answer",
              delta: event.data.deltaContent,
              source: "assistant",
            }),
          );
        }
        break;
      case "tool.execution_start": {
        const tool = event.data.mcpToolName;
        const mcpServer = event.data.mcpConfigServerName ?? event.data.mcpServerName;
        if (mcpServer !== "penge" || tool === undefined) {
          await this.denyTool(session, event.data.toolName, event.data.arguments);
          return;
        }
        try {
          assertMcpToolAllowed(tool);
        } catch {
          await this.denyTool(session, tool, event.data.arguments);
          return;
        }
        session.toolsByCallId.set(event.data.toolCallId, tool);
        session.sink(
          session.emit({
            type: "tool",
            name: tool,
            status: "started",
            detail: "Running an allowlisted read-only Penge evidence tool.",
            startedAt: event.timestamp,
          }),
        );
        await this.store.appendAudit({
          actorId: session.actorId,
          sessionId,
          tool,
          status: "started",
          durationMs: null,
          argumentKeys: redactedArgumentKeys(event.data.arguments),
        });
        break;
      }
      case "tool.execution_complete": {
        const tool = session.toolsByCallId.get(event.data.toolCallId);
        if (tool !== undefined) {
          session.toolsByCallId.delete(event.data.toolCallId);
          assertMcpToolAllowed(tool);
          session.sink(
            session.emit({
              type: "tool",
              name: tool,
              status: event.data.success ? "complete" : "failed",
              detail: event.data.success
                ? "Read-only evidence lookup completed."
                : "Read-only evidence lookup failed.",
            }),
          );
          await this.store.appendAudit({
            actorId: session.actorId,
            sessionId,
            tool,
            status: event.data.success ? "completed" : "error",
            durationMs: null,
            argumentKeys: [],
          });
        }
        break;
      }
      case "session.idle":
        session.sink(
          session.emit({
            type: "completion",
            summary: "Answer completed from bounded Penge evidence.",
            coverage: "partial",
            freshness: "fresh",
            finishReason: event.data.aborted ? "cancelled" : "completed",
          }),
        );
        await this.terminate(sessionId, event.data.aborted ? "cancelled" : "completed", false);
        break;
      case "session.error":
        session.sink(
          session.emit({
            type: "error",
            code: "session_interrupted",
            message: publicErrorMessage(),
            retryable: true,
          }),
        );
        await this.terminate(sessionId, "error", false);
        break;
      default:
        break;
    }
  }

  private async denyTool(session: ActiveSession, tool: string, args: unknown): Promise<void> {
    await this.store.appendAudit({
      actorId: session.actorId,
      sessionId: session.sessionId,
      tool,
      status: "denied",
      durationMs: null,
      argumentKeys: redactedArgumentKeys(args),
    });
    session.sink(
      session.emit({
        type: "error",
        code: "session_interrupted",
        message: "The model requested a tool outside the read-only Penge allowlist.",
        retryable: false,
      }),
    );
    try {
      await session.run.abort();
    } finally {
      await this.terminate(session.sessionId, "error", false);
    }
  }

  private async terminate(
    sessionId: string,
    status: "completed" | "cancelled" | "timeout" | "error",
    emitTimeout: boolean,
  ): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (session === undefined || session.terminal) {
      return;
    }
    session.terminal = true;
    clearTimeout(session.timeout);
    if (emitTimeout) {
      await session.run.abort().catch(() => undefined);
      session.sink(
        session.emit({
          type: "error",
          code: "tool_timeout",
          message: publicErrorMessage(),
          retryable: true,
        }),
      );
    }
    try {
      await session.run.close();
    } finally {
      this.sessions.delete(sessionId);
      await this.store.appendAudit({
        actorId: session.actorId,
        sessionId,
        tool: null,
        status,
        durationMs: Date.now() - session.startedAt,
        argumentKeys: [],
      });
    }
  }
}

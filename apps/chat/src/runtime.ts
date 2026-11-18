import { randomUUID } from "node:crypto";

import type { GitHubTokenProvider, SessionEvent } from "@github/copilot-sdk";
import { z } from "zod/v3";

import { MCP_SOURCE_ALLOWLIST, type ChatConfig } from "./config.js";
import {
  AuthenticationError,
  AuthorizationError,
  FeatureDisabledError,
  HydraFusionUnavailableError,
  SessionLimitError,
} from "./errors.js";
import {
  assertExactToolAllowlist,
  assertMcpToolAllowed,
  McpSourceNameSchema,
  type McpToolName,
} from "./mcp.js";
import type { ActiveCopilotRun, CopilotRuntime } from "./sdk.js";
import { assertPromptIsSafe, ToolPolicyError } from "./security.js";
import { createEventFactory, type StreamEvent, type StreamEventInput } from "./stream.js";
import type { ChatStore } from "./store.js";

export type StreamSink = (event: StreamEvent) => void;

interface TokenProviderFactory {
  providerFor(actorId: string): GitHubTokenProvider;
}

interface ToolEvidence {
  tool: McpToolName;
  coverage: "full" | "partial" | "missing";
  freshness: "fresh" | "stale" | "missing";
}

interface ActiveSession {
  actorId: string;
  sessionId: string;
  startedAt: number;
  touchedAt: number;
  run?: ActiveCopilotRun;
  emit: (event: StreamEventInput) => StreamEvent;
  sink: StreamSink;
  timeout: NodeJS.Timeout;
  terminal: boolean;
  releaseCapacity: () => void;
  launchSettled: boolean;
  teardownSettled: boolean;
  toolsByCallId: Map<string, { tool: McpToolName; allSourcesRequested: boolean }>;
  eventQueue: Promise<void>;
  evidence: ToolEvidence[];
}

type TerminalStatus = "completed" | "cancelled" | "timeout" | "error";

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

const JsonValueSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([
    z.null(),
    z.boolean(),
    z.number(),
    z.string(),
    z.array(JsonValueSchema),
    z.record(z.string(), JsonValueSchema),
  ]),
);

const StructuredContentSchema = z.record(z.string(), JsonValueSchema);
const SOURCE_SET = new Set<string>(MCP_SOURCE_ALLOWLIST);
const SourceCoverageArgumentsSchema = z
  .object({
    source_ids: z
      .array(McpSourceNameSchema)
      .max(MCP_SOURCE_ALLOWLIST.length)
      .refine((sources) => new Set(sources).size === sources.length)
      .optional(),
  })
  .strict();
const SourceCoverageSchema = z.object({
  tool_allowlist: z.array(z.string()).min(1),
  sources: z
    .array(
      z.object({
        id: McpSourceNameSchema,
        coverage: z.object({
          completeness: z.enum(["complete", "partial", "missing"]),
          freshness: z.enum(["fresh", "stale", "unknown"]),
        }),
      }),
    )
    .max(MCP_SOURCE_ALLOWLIST.length)
    .refine((sources) => new Set(sources.map((source) => source.id)).size === sources.length),
  complete: z.boolean(),
  currency: z.enum(["EUR", "DKK"]).optional(),
  _meta: z.object({}).passthrough().optional(),
});

function containsAllSources(sources: readonly string[]): boolean {
  return MCP_SOURCE_ALLOWLIST.every((source) => sources.includes(source));
}

function requestedAllSources(args: unknown): boolean {
  const parsed = SourceCoverageArgumentsSchema.safeParse(args);
  return (
    parsed.success &&
    (parsed.data.source_ids === undefined || containsAllSources(parsed.data.source_ids))
  );
}

function publicErrorMessage(): string {
  return "The chat session was interrupted without retaining its transcript.";
}

function launchErrorEvent(
  error: unknown,
  credentialRejected: boolean,
): Extract<StreamEventInput, { type: "error" }> {
  if (error instanceof AuthenticationError || credentialRejected) {
    return {
      type: "error",
      code: "auth_expired",
      message: "GitHub authorization expired. Reconnect GitHub to continue.",
      retryable: false,
    };
  }
  if (error instanceof HydraFusionUnavailableError) {
    return {
      type: "error",
      code: "hydrafusion_unavailable",
      message: "Copilot Fusion is unavailable for the linked GitHub identity.",
      retryable: false,
    };
  }
  return {
    type: "error",
    code: "session_interrupted",
    message: publicErrorMessage(),
    retryable: true,
  };
}

function collectEvidenceSignals(
  value: JsonValue,
  signals: {
    sources: Set<string>;
    currencies: Set<"EUR" | "DKK">;
    completeness: Set<string>;
    freshness: Set<string>;
    nodes: number;
  },
  depth = 0,
  context: { sourceEntry: boolean } = { sourceEntry: false },
): void {
  if (depth > 8 || signals.nodes >= 10_000) {
    return;
  }
  signals.nodes += 1;
  if (Array.isArray(value)) {
    for (const child of value) {
      collectEvidenceSignals(child, signals, depth + 1, context);
    }
    return;
  }
  if (value !== null && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      if (
        typeof child === "string" &&
        (key === "source" || key === "source_id" || (context.sourceEntry && key === "id")) &&
        SOURCE_SET.has(child)
      ) {
        signals.sources.add(child);
      } else if (key === "currency" && (child === "EUR" || child === "DKK")) {
        signals.currencies.add(child);
      } else if (
        key === "completeness" &&
        typeof child === "string" &&
        ["complete", "full", "partial", "missing"].includes(child)
      ) {
        signals.completeness.add(child);
      } else if (
        key === "freshness" &&
        typeof child === "string" &&
        ["fresh", "stale", "unknown", "missing"].includes(child)
      ) {
        signals.freshness.add(child);
      } else if (key === "complete" && typeof child === "boolean") {
        signals.completeness.add(child ? "complete" : "partial");
      }
      if (key === "sources" && Array.isArray(child)) {
        for (const source of child) {
          collectEvidenceSignals(source, signals, depth + 1, { sourceEntry: true });
        }
      } else {
        collectEvidenceSignals(child, signals, depth + 1, context);
      }
    }
  }
}

export function projectEvidence(
  tool: McpToolName,
  structuredContent: unknown,
  allSourcesRequested = false,
): Extract<StreamEventInput, { type: "evidence" }> {
  const parsed = StructuredContentSchema.safeParse(structuredContent);
  if (!parsed.success) {
    throw new ToolPolicyError(`tool ${tool} returned malformed structuredContent`);
  }

  if (tool === "get_source_coverage") {
    const coverage = SourceCoverageSchema.safeParse(structuredContent);
    if (!coverage.success) {
      throw new ToolPolicyError("get_source_coverage structuredContent is malformed");
    }
    assertExactToolAllowlist(coverage.data.tool_allowlist);
    const sourceNames = coverage.data.sources.map((source) => source.id);
    const freshnessSet = new Set(coverage.data.sources.map((source) => source.coverage.freshness));
    const fullSourceScope = allSourcesRequested && containsAllSources(sourceNames);
    const effectiveCoverage =
      fullSourceScope &&
      coverage.data.complete &&
      coverage.data.sources.every((source) => source.coverage.completeness === "complete")
        ? "full"
        : "partial";
    const effectiveFreshness =
      freshnessSet.has("stale") || freshnessSet.has("unknown")
        ? "stale"
        : freshnessSet.has("fresh")
          ? "fresh"
          : "missing";
    const currency = coverage.data.currency ?? "mixed";
    return {
      type: "evidence",
      title: "Validated get_source_coverage evidence",
      source:
        sourceNames.length > 0 ? sourceNames.sort().join(", ") : "Penge MCP: get_source_coverage",
      coverage: effectiveCoverage,
      freshness: effectiveFreshness,
      currency,
      summary:
        `Validated structured output (${sourceNames.length} allowlisted sources) from the authoritative MCP registration. ` +
        `${fullSourceScope ? "" : "Full source scope was not verified. "}Raw rows were not exposed.`,
    };
  }

  const signals = {
    sources: new Set<string>(),
    currencies: new Set<"EUR" | "DKK">(),
    completeness: new Set<string>(),
    freshness: new Set<string>(),
    nodes: 0,
  };
  collectEvidenceSignals(parsed.data, signals);
  const coverage = signals.completeness.has("missing")
    ? "missing"
    : signals.completeness.has("partial")
      ? "partial"
      : signals.completeness.has("complete") || signals.completeness.has("full")
        ? "full"
        : "partial";
  const freshness = signals.freshness.has("stale")
    ? "stale"
    : signals.freshness.has("unknown") || signals.freshness.has("missing")
      ? "missing"
      : signals.freshness.has("fresh")
        ? "fresh"
        : "missing";
  const currency =
    signals.currencies.size === 1 ? ([...signals.currencies][0] ?? "mixed") : "mixed";
  const sources = [...signals.sources].sort();
  return {
    type: "evidence",
    title: `Validated ${tool} evidence`,
    source: sources.length > 0 ? sources.join(", ") : `Penge MCP: ${tool}`,
    coverage,
    freshness,
    currency,
    summary:
      `Validated structured output (${Object.keys(parsed.data).length} top-level fields, ` +
      `${sources.length} allowlisted sources). Raw rows were not exposed.`,
  };
}

export function summarizeEvidence(evidence: readonly ToolEvidence[]): {
  coverage: "full" | "partial";
  freshness: "fresh" | "stale";
} {
  const verifiedAllSources = evidence.some(
    (item) => item.tool === "get_source_coverage" && item.coverage === "full",
  );
  return {
    coverage:
      verifiedAllSources && evidence.every((item) => item.coverage === "full") ? "full" : "partial",
    freshness:
      evidence.length > 0 && evidence.every((item) => item.freshness === "fresh")
        ? "fresh"
        : "stale",
  };
}

export class ChatRuntime {
  private readonly sessions = new Map<string, ActiveSession>();
  private readonly availableActors = new Set<string>();
  private readonly readinessTasks = new Map<string, Promise<boolean>>();
  private readonly actorGenerations = new Map<string, number>();
  private reservedCapacity = 0;
  private readonly actorCapacity = new Map<string, number>();
  private readonly backgroundTasks = new Set<Promise<void>>();
  private readonly backgroundErrors: unknown[] = [];

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

  isModelAvailable(actorId: string): boolean {
    return this.availableActors.has(actorId);
  }

  async ensureModelAvailable(actorId: string): Promise<boolean> {
    if (!this.config.productionEnabled) {
      return false;
    }
    const current = this.readinessTasks.get(actorId);
    if (current !== undefined) {
      return current;
    }
    const releaseCapacity = this.reserveCapacity(actorId);
    const generation = this.actorGenerations.get(actorId) ?? 0;
    const readiness = this.probeModelAvailability(actorId, generation).finally(() => {
      releaseCapacity();
      if (this.readinessTasks.get(actorId) === readiness) {
        this.readinessTasks.delete(actorId);
      }
    });
    this.readinessTasks.set(actorId, readiness);
    return readiness;
  }

  async invalidateActor(actorId: string): Promise<void> {
    this.actorGenerations.set(actorId, (this.actorGenerations.get(actorId) ?? 0) + 1);
    this.availableActors.delete(actorId);
    await Promise.all(
      [...this.sessions.values()]
        .filter((session) => session.actorId === actorId)
        .map((session) =>
          this.finish(
            session,
            "cancelled",
            {
              type: "completion",
              summary: "The linked GitHub identity changed.",
              coverage: "partial",
              freshness: "stale",
              finishReason: "cancelled",
              assumptions: [],
            },
            true,
          ),
        ),
    );
  }

  async start(actorId: string, question: string, sink: StreamSink): Promise<string> {
    if (!this.config.productionEnabled) {
      throw new FeatureDisabledError("Ask Penge is not enabled");
    }
    assertPromptIsSafe(question);
    const releaseCapacity = this.reserveCapacity(actorId);

    const sessionId = randomUUID();
    const startedAt = Date.now();
    const timeout = setTimeout(() => {
      const session = this.sessions.get(sessionId);
      if (session !== undefined) {
        this.track(
          this.finish(
            session,
            "timeout",
            {
              type: "error",
              code: "tool_timeout",
              message: publicErrorMessage(),
              retryable: true,
            },
            true,
          ),
        );
      }
    }, this.config.requestTimeoutMs);
    timeout.unref();
    const session: ActiveSession = {
      actorId,
      sessionId,
      startedAt,
      touchedAt: startedAt,
      emit: createEventFactory(sessionId, randomUUID),
      sink,
      timeout,
      terminal: false,
      releaseCapacity,
      launchSettled: false,
      teardownSettled: false,
      toolsByCallId: new Map(),
      eventQueue: Promise.resolve(),
      evidence: [],
    };
    this.sessions.set(sessionId, session);
    this.track(
      this.launch(session, question).finally(() => {
        session.launchSettled = true;
        this.releaseWhenSettled(session);
      }),
    );
    return sessionId;
  }

  async cancel(actorId: string, sessionId: string, reason = "user requested stop"): Promise<void> {
    const session = this.ownedSession(actorId, sessionId);
    await this.finish(
      session,
      "cancelled",
      {
        type: "completion",
        summary: reason,
        coverage: "partial",
        freshness: "stale",
        finishReason: "cancelled",
        assumptions: [],
      },
      true,
    );
  }

  async disconnect(actorId: string, sessionId: string): Promise<void> {
    // Transport close can race a terminal event, idle cleanup, or shutdown that already
    // finished the session; disconnect is therefore idempotent for released sessions.
    if (!this.sessions.has(sessionId)) {
      return;
    }
    const session = this.ownedSession(actorId, sessionId);
    await this.finish(session, "cancelled", undefined, true);
  }

  async cleanupIdle(now = Date.now()): Promise<number> {
    const idle = [...this.sessions.values()].filter(
      (session) => now - session.touchedAt >= this.config.idleTimeoutMs,
    );
    await Promise.all(
      idle.map((session) =>
        this.finish(
          session,
          "timeout",
          {
            type: "error",
            code: "tool_timeout",
            message: publicErrorMessage(),
            retryable: true,
          },
          true,
        ),
      ),
    );
    return idle.length;
  }

  async close(): Promise<void> {
    const failures: unknown[] = [];
    const readinessResults = await Promise.allSettled([...this.readinessTasks.values()]);
    for (const result of readinessResults) {
      if (result.status === "rejected") {
        failures.push(result.reason);
      }
    }
    const sessionResults = await Promise.allSettled(
      [...this.sessions.values()].map((session) =>
        this.finish(session, "cancelled", undefined, true),
      ),
    );
    for (const result of sessionResults) {
      if (result.status === "rejected") {
        failures.push(result.reason);
      }
    }
    while (this.backgroundTasks.size > 0) {
      await Promise.allSettled([...this.backgroundTasks]);
    }
    failures.push(...this.backgroundErrors.splice(0));
    if (failures.length > 0) {
      throw new AggregateError(failures, "chat background lifecycle failures");
    }
  }

  private track(task: Promise<void>): void {
    const tracked = task
      .catch((error: unknown) => {
        this.backgroundErrors.push(error);
      })
      .finally(() => {
        this.backgroundTasks.delete(tracked);
      });
    this.backgroundTasks.add(tracked);
  }

  // Capacity covers the whole Copilot/MCP lifetime: a stop during setup must not free the
  // slot until the pending launch has settled, and teardown must finish abort/close first.
  private releaseWhenSettled(session: ActiveSession): void {
    if (session.launchSettled && session.teardownSettled) {
      session.releaseCapacity();
    }
  }

  private reserveCapacity(actorId: string): () => void {
    if (this.reservedCapacity >= this.config.maxConcurrentSessions) {
      throw new SessionLimitError("chat concurrency limit reached");
    }
    const actorReserved = this.actorCapacity.get(actorId) ?? 0;
    if (actorReserved >= this.config.maxConcurrentSessionsPerActor) {
      throw new SessionLimitError("per-actor chat concurrency limit reached");
    }
    this.reservedCapacity += 1;
    this.actorCapacity.set(actorId, actorReserved + 1);
    let released = false;
    return () => {
      if (released) {
        return;
      }
      released = true;
      this.reservedCapacity -= 1;
      const remaining = (this.actorCapacity.get(actorId) ?? 1) - 1;
      if (remaining === 0) {
        this.actorCapacity.delete(actorId);
      } else {
        this.actorCapacity.set(actorId, remaining);
      }
    };
  }

  private async probeModelAvailability(actorId: string, generation: number): Promise<boolean> {
    let run: ActiveCopilotRun | undefined;
    try {
      run = await this.copilot.createRun({
        actorId,
        sessionId: randomUUID(),
        tokenProvider: this.tokenService.providerFor(actorId),
        sink: { onEvent: () => undefined },
      });
      await run.close();
      if ((this.actorGenerations.get(actorId) ?? 0) !== generation) {
        return false;
      }
      this.availableActors.add(actorId);
      return true;
    } catch (error) {
      this.availableActors.delete(actorId);
      if (error instanceof HydraFusionUnavailableError) {
        return false;
      }
      if (run !== undefined) {
        await run.close().catch(() => undefined);
      }
      throw error;
    }
  }

  private async launch(session: ActiveSession, question: string): Promise<void> {
    // The SDK invokes the token provider over its runtime RPC boundary and surfaces a
    // wrapped error, so record rejected credentials here to keep them non-retryable.
    let credentialRejected = false;
    const provider = this.tokenService.providerFor(session.actorId);
    const tokenProvider: GitHubTokenProvider = async (args) => {
      try {
        return await provider(args);
      } catch (error) {
        if (error instanceof AuthenticationError) {
          credentialRejected = true;
        }
        throw error;
      }
    };
    try {
      await this.store.appendAudit({
        actorId: session.actorId,
        sessionId: session.sessionId,
        tool: null,
        status: "started",
        durationMs: null,
        argumentKeys: [],
      });
      if (session.terminal) {
        return;
      }
      const run = await this.copilot.createRun({
        actorId: session.actorId,
        sessionId: session.sessionId,
        tokenProvider,
        sink: {
          onEvent: (event) => this.enqueueSdkEvent(session.sessionId, event),
        },
      });
      if (session.terminal) {
        await run.abort().catch(() => undefined);
        await run.close();
        return;
      }
      session.run = run;
      this.availableActors.add(session.actorId);
      await run.send(question);
    } catch (error) {
      if (error instanceof HydraFusionUnavailableError) {
        this.availableActors.delete(session.actorId);
      }
      await this.finish(session, "error", launchErrorEvent(error, credentialRejected), false);
    }
  }

  private enqueueSdkEvent(sessionId: string, event: SessionEvent): void {
    const session = this.sessions.get(sessionId);
    if (session === undefined || session.terminal) {
      return;
    }
    session.eventQueue = session.eventQueue
      .then(() => this.handleSdkEvent(session, event))
      .catch(async (error: unknown) => {
        try {
          await this.finish(
            session,
            "error",
            {
              type: "error",
              code: "session_interrupted",
              message: publicErrorMessage(),
              retryable: false,
            },
            true,
          );
        } finally {
          if (!(error instanceof ToolPolicyError)) {
            this.backgroundErrors.push(error);
          }
        }
      });
    this.track(session.eventQueue);
  }

  private ownedSession(actorId: string, sessionId: string): ActiveSession {
    const session = this.sessions.get(sessionId);
    if (session === undefined || session.actorId !== actorId) {
      throw new AuthorizationError("chat session does not belong to the authenticated actor");
    }
    return session;
  }

  private async handleSdkEvent(session: ActiveSession, event: SessionEvent): Promise<void> {
    if (session.terminal) {
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
          await this.denyTool(session, event.data.arguments);
          return;
        }
        try {
          assertMcpToolAllowed(tool);
        } catch {
          await this.denyTool(session, event.data.arguments);
          return;
        }
        session.toolsByCallId.set(event.data.toolCallId, {
          tool,
          allSourcesRequested:
            tool === "get_source_coverage" && requestedAllSources(event.data.arguments),
        });
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
          sessionId: session.sessionId,
          tool,
          status: "started",
          durationMs: null,
          argumentKeys: [],
        });
        break;
      }
      case "tool.execution_complete": {
        const call = session.toolsByCallId.get(event.data.toolCallId);
        if (call !== undefined) {
          session.toolsByCallId.delete(event.data.toolCallId);
          const { tool } = call;
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
          if (event.data.success) {
            const evidence = projectEvidence(
              tool,
              event.data.result?.structuredContent,
              call.allSourcesRequested,
            );
            session.evidence.push({
              tool,
              coverage: evidence.coverage,
              freshness: evidence.freshness,
            });
            session.sink(session.emit(evidence));
          } else {
            session.evidence.push({ tool, coverage: "missing", freshness: "missing" });
          }
          await this.store.appendAudit({
            actorId: session.actorId,
            sessionId: session.sessionId,
            tool,
            status: event.data.success ? "completed" : "error",
            durationMs: null,
            argumentKeys: [],
          });
        }
        break;
      }
      case "session.idle":
        const evidenceSummary = summarizeEvidence(session.evidence);
        await this.finish(
          session,
          event.data.aborted ? "cancelled" : "completed",
          {
            type: "completion",
            summary: event.data.aborted
              ? "Answer stopped before completion."
              : evidenceSummary.coverage === "partial"
                ? "Answer completed with partial evidence coverage."
                : "Answer completed from bounded Penge evidence.",
            ...evidenceSummary,
            finishReason: event.data.aborted ? "cancelled" : "completed",
            assumptions: [],
          },
          false,
        );
        break;
      case "session.error":
        await this.finish(
          session,
          "error",
          {
            type: "error",
            code: "session_interrupted",
            message: publicErrorMessage(),
            retryable: true,
          },
          false,
        );
        break;
      default:
        break;
    }
  }

  private async denyTool(session: ActiveSession, _args: unknown): Promise<void> {
    const deniedTool = "denied_untrusted_tool";
    await this.store.appendAudit({
      actorId: session.actorId,
      sessionId: session.sessionId,
      tool: deniedTool,
      status: "denied",
      durationMs: null,
      argumentKeys: [],
    });
    await this.finish(
      session,
      "error",
      {
        type: "error",
        code: "session_interrupted",
        message: "The model requested a tool outside the read-only Penge allowlist.",
        retryable: false,
      },
      true,
    );
  }

  private async finish(
    session: ActiveSession,
    status: TerminalStatus,
    terminalEvent: StreamEventInput | undefined,
    abort: boolean,
  ): Promise<void> {
    if (session.terminal) {
      return;
    }
    session.terminal = true;
    clearTimeout(session.timeout);
    this.sessions.delete(session.sessionId);
    try {
      await this.teardown(session, status, terminalEvent, abort);
    } finally {
      session.teardownSettled = true;
      this.releaseWhenSettled(session);
    }
  }

  private async teardown(
    session: ActiveSession,
    status: TerminalStatus,
    terminalEvent: StreamEventInput | undefined,
    abort: boolean,
  ): Promise<void> {
    const failures: unknown[] = [];
    if (abort && session.run !== undefined) {
      try {
        await session.run.abort();
      } catch (error) {
        failures.push(error);
      }
    }
    if (terminalEvent !== undefined) {
      try {
        session.sink(session.emit(terminalEvent));
      } catch (error) {
        failures.push(error);
      }
    }
    if (session.run !== undefined) {
      try {
        await session.run.close();
      } catch (error) {
        failures.push(error);
      }
    }
    try {
      await this.store.appendAudit({
        actorId: session.actorId,
        sessionId: session.sessionId,
        tool: null,
        status,
        durationMs: Date.now() - session.startedAt,
        argumentKeys: [],
      });
    } catch (error) {
      failures.push(error);
    }
    if (failures.length > 0) {
      throw new AggregateError(failures, `chat session ${status} cleanup failed`);
    }
  }
}

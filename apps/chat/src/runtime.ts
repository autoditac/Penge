import { z } from "zod/v3";

export const SessionStateSchema = z.object({
  sessionId: z.string().min(1),
  actorId: z.string().min(1),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
  status: z.enum(["active", "completed", "cancelled", "timeout"]),
  reason: z.string().nullable().default(null),
  toolNames: z.array(z.string()).default([]),
  transcriptStored: z.literal(false),
});

export type SessionState = z.infer<typeof SessionStateSchema>;

export class SessionRuntime {
  private readonly sessions = new Map<string, SessionState>();

  createSession(actorId: string, sessionId: string): SessionState {
    const now = new Date().toISOString();
    const next = SessionStateSchema.parse({
      sessionId,
      actorId,
      createdAt: now,
      updatedAt: now,
      status: "active",
      reason: null,
      toolNames: [],
      transcriptStored: false,
    });
    this.sessions.set(sessionId, next);
    return next;
  }

  getSession(sessionId: string): SessionState | undefined {
    return this.sessions.get(sessionId);
  }

  assertActorIsolation(sessionId: string, actorId: string): void {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`session ${sessionId} does not exist`);
    }
    if (session.actorId !== actorId) {
      throw new Error(`session ${sessionId} is not owned by actor ${actorId}`);
    }
  }

  recordTool(sessionId: string, toolName: string): SessionState {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`session ${sessionId} does not exist`);
    }
    const updated: SessionState = {
      ...session,
      updatedAt: new Date().toISOString(),
      toolNames: [...session.toolNames, toolName],
    };
    this.sessions.set(sessionId, updated);
    return updated;
  }

  completeSession(sessionId: string, reason?: string): SessionState {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`session ${sessionId} does not exist`);
    }
    const updated: SessionState = {
      ...session,
      updatedAt: new Date().toISOString(),
      status: "completed",
      reason: reason ?? null,
    };
    this.sessions.set(sessionId, updated);
    return updated;
  }

  cancelSession(sessionId: string, reason: string): SessionState {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`session ${sessionId} does not exist`);
    }
    const updated: SessionState = {
      ...session,
      updatedAt: new Date().toISOString(),
      status: "cancelled",
      reason,
    };
    this.sessions.set(sessionId, updated);
    return updated;
  }

  timeoutSession(sessionId: string, reason: string): SessionState {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`session ${sessionId} does not exist`);
    }
    const updated: SessionState = {
      ...session,
      updatedAt: new Date().toISOString(),
      status: "timeout",
      reason,
    };
    this.sessions.set(sessionId, updated);
    return updated;
  }

  cleanupIdle(idleTimeoutMs: number, now = Date.now()): SessionState[] {
    const expired: SessionState[] = [];
    for (const [sessionId, session] of this.sessions.entries()) {
      const updatedAtMs = new Date(session.updatedAt).getTime();
      if (now - updatedAtMs > idleTimeoutMs && session.status === "active") {
        const timedOut = this.timeoutSession(sessionId, "idle timeout");
        expired.push(timedOut);
      }
    }
    return expired;
  }
}

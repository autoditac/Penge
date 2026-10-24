import type { ChatConfig } from "../src/config.js";
import type { EncryptedEnvelope } from "../src/identity.js";
import type { AuditEvent, ChatStore, LockedOAuthActorStore, OAuthLink } from "../src/store.js";

export function syntheticConfig(overrides: Partial<ChatConfig> = {}): ChatConfig {
  return {
    httpHost: "127.0.0.1",
    httpPort: 0,
    publicApiBase: "https://penge.example.test/api/",
    publicAppOrigin: "https://penge.example.test",
    trustedProxyIssuer: "https://accounts.google.com",
    identityPepper: "i".repeat(32),
    proxySharedSecret: "p".repeat(32),
    tokenEncryptionKeyring: {
      currentKeyId: "key-2",
      keys: {
        "key-1": Buffer.alloc(32, 1),
        "key-2": Buffer.alloc(32, 2),
      },
    },
    githubClientId: "synthetic-client",
    githubClientSecret: "synthetic-client-secret",
    githubOAuthAuthorizeUrl: "https://github.com/login/oauth/authorize",
    githubOAuthTokenUrl: "https://github.com/login/oauth/access_token",
    githubApiUrl: "https://api.github.com",
    model: "hydrafusion",
    fallbackModel: undefined,
    productionEnabled: true,
    mcpToolContractVersion: "issue-344-v1",
    mcpCommand: "pnpm",
    mcpArgs: ["--filter", "@penge/mcp", "start"],
    mcpWorkingDirectory: "/srv/penge",
    mcpDatabaseUrlFile: "/run/secrets/penge-db-url-v1",
    mcpDuckdbPath: "/srv/penge/data/analytics.duckdb",
    mcpVaultRoot: "/srv/penge/data/vault",
    mcpLogDir: "/srv/penge/logs/mcp",
    databaseUrl: "postgresql://penge_chat_oauth@127.0.0.1:5432/penge",
    databaseRole: "penge_chat_oauth",
    copilotBaseDirectory: "/tmp/penge-chat-tests",
    requestTimeoutMs: 1_000,
    idleTimeoutMs: 500,
    httpRequestTimeoutMs: 5_000,
    maxConcurrentSessions: 2,
    maxConcurrentSessionsPerActor: 1,
    ...overrides,
  };
}

export class MemoryChatStore implements ChatStore {
  readonly states = new Map<
    string,
    { actorId: string; envelope: EncryptedEnvelope; expiresAt: string }
  >();
  readonly links = new Map<string, OAuthLink>();
  readonly audits: AuditEvent[] = [];
  private readonly oauthActorLocks = new Map<string, Promise<void>>();

  async withOAuthActorLock<T>(
    actorId: string,
    operation: (lockedStore: LockedOAuthActorStore) => Promise<T>,
  ): Promise<T> {
    const previous = this.oauthActorLocks.get(actorId) ?? Promise.resolve();
    let release = (): void => undefined;
    const current = new Promise<void>((resolve) => {
      release = resolve;
    });
    this.oauthActorLocks.set(actorId, current);
    await previous;
    try {
      return await operation({
        putState: async (stateHash, stateEnvelope, expiresAt) => {
          await this.putOAuthState(actorId, stateHash, stateEnvelope, expiresAt);
        },
        consumeState: async (stateHash, now) => this.consumeOAuthState(actorId, stateHash, now),
        deletePendingStates: async () => {
          for (const [stateHash, state] of this.states) {
            if (state.actorId === actorId) {
              this.states.delete(stateHash);
            }
          }
        },
        getLink: async () => this.getOAuthLink(actorId),
        upsertLink: async (githubUserId, githubLogin, tokenEnvelope) => {
          await this.upsertOAuthLink(actorId, githubUserId, githubLogin, tokenEnvelope);
        },
        deleteLink: async () => {
          await this.deleteOAuthLink(actorId);
        },
      });
    } finally {
      release();
      if (this.oauthActorLocks.get(actorId) === current) {
        this.oauthActorLocks.delete(actorId);
      }
    }
  }

  async withOAuthCallbackLock<T>(
    actorId: string,
    stateHash: string,
    operation: (
      stateEnvelope: EncryptedEnvelope | null,
      lockedStore: LockedOAuthActorStore,
    ) => Promise<T>,
  ): Promise<T> {
    return this.withOAuthActorLock(actorId, async (lockedStore) => {
      const stateEnvelope = await lockedStore.consumeState(stateHash);
      return operation(stateEnvelope, lockedStore);
    });
  }

  async putOAuthState(
    actorId: string,
    stateHash: string,
    stateEnvelope: EncryptedEnvelope,
    expiresAt: string,
  ): Promise<void> {
    for (const [key, value] of this.states) {
      if (value.actorId === actorId || new Date(value.expiresAt).getTime() <= Date.now()) {
        this.states.delete(key);
      }
    }
    this.states.set(stateHash, { actorId, envelope: stateEnvelope, expiresAt });
  }

  async consumeOAuthState(
    actorId: string,
    stateHash: string,
    now = new Date(),
  ): Promise<EncryptedEnvelope | null> {
    const value = this.states.get(stateHash);
    this.states.delete(stateHash);
    if (
      value === undefined ||
      value.actorId !== actorId ||
      new Date(value.expiresAt).getTime() <= now.getTime()
    ) {
      return null;
    }
    return value.envelope;
  }

  async upsertOAuthLink(
    actorId: string,
    githubUserId: number,
    githubLogin: string,
    tokenEnvelope: EncryptedEnvelope,
  ): Promise<void> {
    const conflictingActor = [...this.links.values()].find(
      (link) => link.githubUserId === githubUserId && link.actorId !== actorId,
    );
    if (conflictingActor !== undefined) {
      throw new Error("synthetic unique github_user_id violation");
    }
    this.links.set(actorId, {
      actorId,
      githubUserId,
      githubLogin,
      tokenEnvelope,
      updatedAt: new Date().toISOString(),
    });
  }

  async getOAuthLink(actorId: string): Promise<OAuthLink | null> {
    return this.links.get(actorId) ?? null;
  }

  async deleteOAuthLink(actorId: string): Promise<void> {
    this.links.delete(actorId);
  }

  async appendAudit(event: AuditEvent): Promise<void> {
    this.audits.push(event);
  }

  async close(): Promise<void> {}
}

import type { ChatConfig } from "../src/config.js";
import type { EncryptedEnvelope } from "../src/identity.js";
import type { AuditEvent, ChatStore, OAuthLink } from "../src/store.js";

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

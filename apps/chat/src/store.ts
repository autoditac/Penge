import pg from "pg";
import { z } from "zod/v3";

import { DatabasePolicyError } from "./errors.js";
import type { EncryptedEnvelope } from "./identity.js";

const { Pool } = pg;

export const OAuthLinkSchema = z
  .object({
    actorId: z.string().min(1),
    githubUserId: z.number().int().positive(),
    githubLogin: z.string().min(1),
    tokenEnvelope: z.unknown(),
    updatedAt: z.string().datetime(),
  })
  .strict();

export const AuditEventSchema = z
  .object({
    actorId: z.string().min(1),
    sessionId: z.string().min(1).nullable(),
    tool: z.string().min(1).nullable(),
    status: z.enum(["started", "completed", "cancelled", "timeout", "error", "denied"]),
    durationMs: z.number().int().nonnegative().nullable(),
    argumentKeys: z.array(z.string().regex(/^[a-zA-Z0-9_.-]{1,64}$/)).max(32),
  })
  .strict();

export type OAuthLink = z.infer<typeof OAuthLinkSchema>;
export type AuditEvent = z.infer<typeof AuditEventSchema>;

export interface ChatStore {
  putOAuthState(
    actorId: string,
    stateHash: string,
    stateEnvelope: EncryptedEnvelope,
    expiresAt: string,
  ): Promise<void>;
  consumeOAuthState(
    actorId: string,
    stateHash: string,
    now?: Date,
  ): Promise<EncryptedEnvelope | null>;
  upsertOAuthLink(
    actorId: string,
    githubUserId: number,
    githubLogin: string,
    tokenEnvelope: EncryptedEnvelope,
  ): Promise<void>;
  getOAuthLink(actorId: string): Promise<OAuthLink | null>;
  appendAudit(event: AuditEvent): Promise<void>;
  close(): Promise<void>;
}

interface Queryable {
  query(
    query: string,
    values?: readonly unknown[],
  ): Promise<{ rows: Array<{ table_name: string }> }>;
}

export class PostgresChatStore implements ChatStore {
  private constructor(private readonly pool: pg.Pool) {}

  static async connect(databaseUrl: string, expectedRole: string): Promise<PostgresChatStore> {
    const pool = new Pool({
      connectionString: databaseUrl,
      max: 4,
      application_name: "penge-chat",
    });
    try {
      const result = await pool.query<{ role: string }>("SELECT current_user::text AS role");
      if (result.rows[0]?.role !== expectedRole) {
        throw new DatabasePolicyError(
          `chat database connection must use role ${expectedRole}, got ${result.rows[0]?.role ?? "unknown"}`,
        );
      }
      await assertNoFinanceTableAccess(pool);
      return new PostgresChatStore(pool);
    } catch (error) {
      await pool.end();
      throw error;
    }
  }

  async putOAuthState(
    actorId: string,
    stateHash: string,
    stateEnvelope: EncryptedEnvelope,
    expiresAt: string,
  ): Promise<void> {
    await this.pool.query(
      `INSERT INTO chat_oauth_state
         (state_hash, actor_id, state_envelope, expires_at)
       VALUES ($1, $2, $3::jsonb, $4)`,
      [stateHash, actorId, JSON.stringify(stateEnvelope), expiresAt],
    );
  }

  async consumeOAuthState(
    actorId: string,
    stateHash: string,
    now = new Date(),
  ): Promise<EncryptedEnvelope | null> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query<{
        state_envelope: EncryptedEnvelope;
        expires_at: Date;
      }>(
        `DELETE FROM chat_oauth_state
         WHERE state_hash = $1 AND actor_id = $2
         RETURNING state_envelope, expires_at`,
        [stateHash, actorId],
      );
      await client.query("COMMIT");
      const row = result.rows[0];
      if (row === undefined || row.expires_at.getTime() <= now.getTime()) {
        return null;
      }
      return row.state_envelope;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async upsertOAuthLink(
    actorId: string,
    githubUserId: number,
    githubLogin: string,
    tokenEnvelope: EncryptedEnvelope,
  ): Promise<void> {
    await this.pool.query(
      `INSERT INTO chat_oauth_link
         (actor_id, github_user_id, github_login, token_envelope)
       VALUES ($1, $2, $3, $4::jsonb)
       ON CONFLICT (actor_id) DO UPDATE SET
         github_user_id = EXCLUDED.github_user_id,
         github_login = EXCLUDED.github_login,
         token_envelope = EXCLUDED.token_envelope,
         updated_at = now()`,
      [actorId, githubUserId, githubLogin, JSON.stringify(tokenEnvelope)],
    );
  }

  async getOAuthLink(actorId: string): Promise<OAuthLink | null> {
    const result = await this.pool.query<{
      actor_id: string;
      github_user_id: string;
      github_login: string;
      token_envelope: unknown;
      updated_at: Date;
    }>(
      `SELECT actor_id, github_user_id, github_login, token_envelope, updated_at
       FROM chat_oauth_link WHERE actor_id = $1`,
      [actorId],
    );
    const row = result.rows[0];
    return row === undefined
      ? null
      : OAuthLinkSchema.parse({
          actorId: row.actor_id,
          githubUserId: Number(row.github_user_id),
          githubLogin: row.github_login,
          tokenEnvelope: row.token_envelope,
          updatedAt: row.updated_at.toISOString(),
        });
  }

  async appendAudit(event: AuditEvent): Promise<void> {
    const parsed = AuditEventSchema.parse(event);
    await this.pool.query(
      `INSERT INTO chat_audit_event
         (actor_id, session_id, tool_name, status, duration_ms, argument_keys)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb)`,
      [
        parsed.actorId,
        parsed.sessionId,
        parsed.tool,
        parsed.status,
        parsed.durationMs,
        JSON.stringify(parsed.argumentKeys),
      ],
    );
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}

export async function assertNoFinanceTableAccess(queryable: Queryable): Promise<void> {
  const result = await queryable.query(
    `SELECT table_name
     FROM information_schema.tables
     WHERE table_schema = 'public'
       AND table_name <> ALL($1::text[])
       AND has_table_privilege(
         current_user,
         format('%I.%I', table_schema, table_name),
         'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
       )`,
    [["chat_oauth_state", "chat_oauth_link", "chat_audit_event"]],
  );
  if (result.rows.length > 0) {
    throw new DatabasePolicyError(
      `chat database role has unexpected table access: ${result.rows
        .map((row) => row.table_name)
        .sort()
        .join(", ")}`,
    );
  }
}

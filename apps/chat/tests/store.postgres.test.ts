import { Client } from "pg";
import { describe, expect, it, vi } from "vitest";

import { GitHubOAuthFlow, UserTokenService } from "../src/oauth.js";
import { PostgresChatStore } from "../src/store.js";
import { syntheticConfig } from "./helpers.js";

const databaseUrl = process.env.PENGE_CHAT_STORE_TEST_DATABASE_URL;
const adminUrl = process.env.PENGE_CHAT_STORE_TEST_ADMIN_URL;
const expectedRole = process.env.PENGE_CHAT_STORE_TEST_ROLE;
const expectsPrivilegeRejection = process.env.PENGE_CHAT_STORE_EXPECT_PRIVILEGE_REJECTION === "1";
const canRunFunctional =
  databaseUrl !== undefined &&
  adminUrl !== undefined &&
  expectedRole !== undefined &&
  !expectsPrivilegeRejection;

describe("PostgreSQL chat-role isolation", () => {
  it.runIf(databaseUrl !== undefined && expectedRole !== undefined && expectsPrivilegeRejection)(
    "rejects a column-only grant on a non-chat table",
    async () => {
      await expect(PostgresChatStore.connect(databaseUrl!, expectedRole!)).rejects.toThrow(
        /public\.finance_shadow/,
      );
    },
  );

  it.runIf(canRunFunctional)(
    "durably consumes OAuth state before a later callback failure",
    async () => {
      const store = await PostgresChatStore.connect(databaseUrl!, expectedRole!);
      const fetcher = vi.fn(async () => new Response("upstream failed", { status: 502 }));
      const flow = new GitHubOAuthFlow(syntheticConfig(), store, fetcher as typeof fetch);
      const actorId = "actor_0123456789abcdef0123456789abcdef";
      const state = new URL(await flow.begin(actorId)).searchParams.get("state")!;
      try {
        await expect(flow.complete(actorId, state, "synthetic-code")).rejects.toThrow();
        await expect(flow.complete(actorId, state, "synthetic-code")).rejects.toThrow(
          /already consumed/,
        );
        expect(fetcher).toHaveBeenCalledTimes(1);
      } finally {
        await store.close();
      }
    },
  );

  it.runIf(canRunFunctional)("bounds waits for a contended actor lock", async () => {
    const actorId = "actor_0123456789abcdef0123456789abcdef";
    const blocker = new Client({ connectionString: adminUrl });
    const store = await PostgresChatStore.connect(databaseUrl!, expectedRole!, {
      timeoutMs: 100,
      connectionTimeoutMs: 1_000,
    });
    await blocker.connect();
    try {
      await blocker.query("SELECT pg_advisory_lock(hashtextextended($1, 0))", [actorId]);
      await expect(store.withOAuthActorLock(actorId, async () => undefined)).rejects.toThrow();
    } finally {
      await blocker.query("SELECT pg_advisory_unlock(hashtextextended($1, 0))", [actorId]);
      await blocker.end();
      await store.close();
    }
  });

  it.runIf(canRunFunctional)(
    "keeps actor serialization through a slow successful token refresh",
    async () => {
      const config = syntheticConfig();
      const store = await PostgresChatStore.connect(databaseUrl!, expectedRole!, {
        timeoutMs: 500,
        connectionTimeoutMs: 1_000,
        oauthTransactionTimeoutMs: 1_000,
      });
      const actorId = "actor_abcdef0123456789abcdef0123456789";
      const initialResponses = [
        new Response(
          JSON.stringify({
            access_token: "short-access",
            refresh_token: "synthetic-refresh",
            expires_in: 10,
            refresh_token_expires_in: 10_000,
            token_type: "bearer",
          }),
          { headers: { "content-type": "application/json" } },
        ),
        new Response(JSON.stringify({ id: 84, login: "slow-refresh-user" }), {
          headers: { "content-type": "application/json" },
        }),
      ];
      const flow = new GitHubOAuthFlow(
        config,
        store,
        vi.fn(async () => initialResponses.shift()!) as typeof fetch,
      );
      try {
        const state = new URL(await flow.begin(actorId)).searchParams.get("state")!;
        await flow.complete(actorId, state, "synthetic-code");
        const refresh = vi.fn(async () => {
          await new Promise((resolve) => setTimeout(resolve, 120));
          return new Response(
            JSON.stringify({
              access_token: "rotated-access",
              refresh_token: "rotated-refresh",
              expires_in: 7_200,
              token_type: "bearer",
            }),
            { headers: { "content-type": "application/json" } },
          );
        }) as typeof fetch;
        const token = await new UserTokenService(config, store, refresh).providerFor(actorId)({
          host: "github.com",
          sessionId: "slow-refresh",
          reason: "refresh",
        });
        expect(token).toMatchObject({ kind: "token", accessToken: "rotated-access" });
        expect(refresh).toHaveBeenCalledOnce();
      } finally {
        await store.close();
      }
    },
  );

  it.runIf(canRunFunctional)("observes an idle pool client failure", async () => {
    let observedError: Error | undefined;
    let resolveError: (() => void) | undefined;
    const errorObserved = new Promise<void>((resolve) => {
      resolveError = resolve;
    });
    const store = await PostgresChatStore.connect(databaseUrl!, expectedRole!, {
      onPoolError: (error) => {
        observedError = error;
        resolveError?.();
      },
    });
    const admin = new Client({ connectionString: adminUrl });
    await admin.connect();
    try {
      const terminated = await admin.query<{ terminated: boolean }>(
        `SELECT pg_terminate_backend(pid) AS terminated
         FROM pg_stat_activity
         WHERE application_name = 'penge-chat'
           AND usename = $1
           AND state = 'idle'
         ORDER BY backend_start DESC
         LIMIT 1`,
        [expectedRole],
      );
      expect(terminated.rows).toEqual([{ terminated: true }]);
      await Promise.race([
        errorObserved,
        new Promise<never>((_resolve, reject) =>
          setTimeout(() => reject(new Error("pool error was not observed")), 2_000),
        ),
      ]);
      expect(observedError).toBeInstanceOf(Error);
    } finally {
      await admin.end();
      await store.close();
    }
  });
});

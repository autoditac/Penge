import { Client } from "pg";
import { describe, expect, it, vi } from "vitest";

import { GitHubOAuthFlow } from "../src/oauth.js";
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

import { describe, expect, it } from "vitest";

import { PostgresChatStore } from "../src/store.js";

const databaseUrl = process.env.PENGE_CHAT_STORE_TEST_DATABASE_URL;
const expectedRole = process.env.PENGE_CHAT_STORE_TEST_ROLE;

describe("PostgreSQL chat-role isolation", () => {
  it.runIf(databaseUrl !== undefined && expectedRole !== undefined)(
    "rejects a column-only grant on a non-chat table",
    async () => {
      await expect(PostgresChatStore.connect(databaseUrl!, expectedRole!)).rejects.toThrow(
        /public\.finance_shadow/,
      );
    },
  );
});

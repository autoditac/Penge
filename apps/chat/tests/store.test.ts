import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { assertNoFinanceTableAccess } from "../src/store.js";

describe("database isolation contract", () => {
  it("fails startup if the service role can access a finance table", async () => {
    const queryable = {
      query: async () => ({ rows: [{ table_name: "raw_transaction" }] }),
    };
    await expect(assertNoFinanceTableAccess(queryable)).rejects.toThrow(
      /unexpected table access: raw_transaction/,
    );
  });

  it("migration creates encrypted OAuth/audit tables and grants only those tables", () => {
    const migration = readFileSync(
      new URL("../migrations/versions/0001_create_chat_oauth_storage.py", import.meta.url),
      "utf8",
    );
    expect(migration).toContain("state_hash");
    expect(migration).toContain("state_envelope");
    expect(migration).toContain("token_envelope");
    expect(migration).toContain("chat_audit_event");
    expect(migration).not.toContain("CREATE ROLE");
    expect(migration).not.toContain("DROP ROLE");
    expect(migration).not.toContain("REVOKE ALL ON ALL TABLES");
    expect(migration).not.toContain("google_subject");
    expect(migration).not.toContain("code_verifier");
  });

  it("keeps the chat migration off the finance Alembic chain", () => {
    const financeMigration = readFileSync(
      new URL(
        "../../../migrations/versions/cb332a4e91df_add_public_merchant_reference_index.py",
        import.meta.url,
      ),
      "utf8",
    );
    expect(financeMigration).not.toContain("chat_oauth");
  });
});

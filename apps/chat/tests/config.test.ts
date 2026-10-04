import { describe, expect, it } from "vitest";

import { DEFAULT_MCP_ALLOWLIST, loadConfig } from "../src/config.js";

describe("chat config", () => {
  it("loads defaults and validates the allowlist", () => {
    const config = loadConfig({
      PENGE_CHAT_SESSION_SECRET: "12345678901234567890123456789012",
      PENGE_CHAT_TOKEN_ENCRYPTION_KEY: "12345678901234567890123456789012",
      PENGE_CHAT_GOOGLE_PROXY_ISSUER: "http://127.0.0.1:4180",
      PENGE_CHAT_GITHUB_CLIENT_ID: "client-id",
      PENGE_CHAT_GITHUB_CLIENT_SECRET: "secret",
      PENGE_CHAT_GITHUB_APP_ID: "app-id",
      PENGE_CHAT_GITHUB_APP_PRIVATE_KEY: "private-key",
      PENGE_CHAT_DB_URL: "postgresql://chat:secret@127.0.0.1:5432/penge_chat",
      PENGE_CHAT_DB_ROLE: "chat_oauth_only",
      PENGE_CHAT_DB_ALLOWED_TABLES: [
        "chat_oauth_state",
        "chat_oauth_link",
        "chat_oauth_nonce",
      ].join(","),
    });

    expect(config.model).toBe("hydrafusion");
    expect(config.mcpAllowlist).toEqual([...DEFAULT_MCP_ALLOWLIST]);
    expect(config.loopbackOnly).toBe(true);
  });

  it("rejects invalid configuration", () => {
    expect(() =>
      loadConfig({
        PENGE_CHAT_SESSION_SECRET: "short",
        PENGE_CHAT_TOKEN_ENCRYPTION_KEY: "short",
        PENGE_CHAT_GOOGLE_PROXY_ISSUER: "http://127.0.0.1:4180",
        PENGE_CHAT_GITHUB_CLIENT_ID: "client",
        PENGE_CHAT_GITHUB_CLIENT_SECRET: "secret",
        PENGE_CHAT_GITHUB_APP_ID: "app",
        PENGE_CHAT_GITHUB_APP_PRIVATE_KEY: "key",
        PENGE_CHAT_DB_URL: "postgresql://chat:secret@127.0.0.1:5432/penge_chat",
        PENGE_CHAT_DB_ROLE: "chat_oauth_only",
      }),
    ).toThrow();
  });
});

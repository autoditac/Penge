import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { loadConfig } from "../src/config.js";

const directories: string[] = [];

function secret(directory: string, name: string, content: string): string {
  const path = join(directory, name);
  writeFileSync(path, content, { mode: 0o600 });
  return path;
}

function validEnv(): NodeJS.ProcessEnv {
  const directory = mkdtempSync(join(tmpdir(), "penge-chat-config-"));
  directories.push(directory);
  return {
    PENGE_CHAT_MODEL: "hydrafusion",
    PENGE_CHAT_PUBLIC_ORIGIN: "https://penge.example.test",
    PENGE_CHAT_TRUSTED_PROXY_ISSUER: "https://accounts.google.com",
    PENGE_CHAT_IDENTITY_PEPPER_FILE: secret(directory, "identity", "i".repeat(32)),
    PENGE_CHAT_PROXY_SHARED_SECRET_FILE: secret(directory, "proxy", "p".repeat(32)),
    PENGE_CHAT_TOKEN_KEYRING_FILE: secret(
      directory,
      "keyring",
      JSON.stringify({
        currentKeyId: "v2",
        keys: {
          v1: Buffer.alloc(32, 1).toString("base64"),
          v2: Buffer.alloc(32, 2).toString("base64"),
        },
      }),
    ),
    PENGE_CHAT_GITHUB_CLIENT_ID: "client",
    PENGE_CHAT_GITHUB_CLIENT_SECRET_FILE: secret(directory, "github", "g".repeat(32)),
    PENGE_CHAT_MCP_WORKING_DIRECTORY: "/srv/penge",
    PENGE_CHAT_MCP_DATABASE_URL: "postgresql://mcp@127.0.0.1/penge",
    PENGE_CHAT_MCP_DUCKDB_PATH: "/srv/penge/data/analytics.duckdb",
    PENGE_CHAT_MCP_VAULT_ROOT: "/srv/penge/data/vault",
    PENGE_CHAT_MCP_LOG_DIR: "/srv/penge/logs/mcp",
    PENGE_CHAT_DATABASE_URL: "postgresql://penge_chat_oauth@127.0.0.1/penge",
    PENGE_CHAT_COPILOT_BASE_DIRECTORY: "/run/penge-chat/copilot",
  };
}

afterEach(() => {
  for (const directory of directories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("chat config", () => {
  it("accepts loopback listener with an external HTTPS browser origin and rotated keys", () => {
    const config = loadConfig(validEnv());
    expect(config.httpHost).toBe("127.0.0.1");
    expect(config.publicOrigin).toBe("https://penge.example.test");
    expect(Object.keys(config.tokenEncryptionKeyring.keys)).toEqual(["v1", "v2"]);
  });

  it("fails closed for malformed feature flags and fallback models", () => {
    expect(() => loadConfig({ ...validEnv(), PENGE_CHAT_ENABLE_PRODUCTION: "yes" })).toThrow(
      /must be 0, 1, or unset/,
    );
    expect(() => loadConfig({ ...validEnv(), PENGE_CHAT_FALLBACK_MODEL: "gpt-5.4" })).toThrow(
      /must be unset/,
    );
  });

  it("rejects insecure public origins and permissive secret files", () => {
    expect(() =>
      loadConfig({ ...validEnv(), PENGE_CHAT_PUBLIC_ORIGIN: "http://penge.example.test" }),
    ).toThrow(/HTTPS/);
    const env = validEnv();
    chmodSync(env.PENGE_CHAT_IDENTITY_PEPPER_FILE!, 0o644);
    expect(() => loadConfig(env)).toThrow(/group- or world-accessible/);
  });
});

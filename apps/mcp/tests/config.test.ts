import { chmodSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ConfigError, loadConfig } from "../src/config.js";

describe("loadConfig", () => {
  it("parses a valid environment", () => {
    const cfg = loadConfig({
      PENGE_DB_URL: "postgres://penge:penge@localhost:5432/penge",
      PENGE_DUCKDB_PATH: "/var/lib/penge/marts.duckdb",
      PENGE_MCP_ACTOR_ID: "actor_01ARZ3NDEKTSV4RRFFQ69G5FAV",
      PENGE_MCP_SESSION_ID: "session_01ARZ3NDEKTSV4RRFFQ69G5FAW",
    });
    expect(cfg.databaseUrl).toBe("postgres://penge:penge@localhost:5432/penge");
    expect(cfg.duckdbPath).toBe("/var/lib/penge/marts.duckdb");
    expect(cfg.logDir).toBe("logs/mcp");
    expect(cfg.actorId).toBe("actor_01ARZ3NDEKTSV4RRFFQ69G5FAV");
    expect(cfg.sessionId).toBe("session_01ARZ3NDEKTSV4RRFFQ69G5FAW");
  });

  it("rejects missing PENGE_DB_URL", () => {
    expect(() => loadConfig({ PENGE_DUCKDB_PATH: "x.duckdb" } as NodeJS.ProcessEnv)).toThrow(
      ConfigError,
    );
  });

  it("reads the database URL from an owner-only regular file", () => {
    const dir = mkdtempSync(join(tmpdir(), "penge-mcp-config-"));
    const file = join(dir, "database-url");
    writeFileSync(file, `${new URL("postgresql://localhost/penge").toString()}\n`, { mode: 0o600 });
    try {
      const cfg = loadConfig({
        PENGE_DB_URL_FILE: file,
        PENGE_DUCKDB_PATH: "x.duckdb",
      });
      expect(cfg.databaseUrl).toBe(new URL("postgresql://localhost/penge").toString());
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("rejects ambiguous direct and file database URL configuration", () => {
    expect(() =>
      loadConfig({
        PENGE_DB_URL: new URL("postgresql://localhost/penge").toString(),
        PENGE_DB_URL_FILE: "/run/secrets/penge-db-url",
        PENGE_DUCKDB_PATH: "x.duckdb",
      }),
    ).toThrow(/mutually exclusive/);
  });

  it("rejects database URL files accessible to other users", () => {
    const dir = mkdtempSync(join(tmpdir(), "penge-mcp-config-"));
    const file = join(dir, "database-url");
    writeFileSync(file, new URL("postgresql://localhost/penge").toString(), { mode: 0o600 });
    chmodSync(file, 0o640);
    try {
      expect(() =>
        loadConfig({
          PENGE_DB_URL_FILE: file,
          PENGE_DUCKDB_PATH: "x.duckdb",
        }),
      ).toThrow(/inaccessible to others/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("rejects a symlink database URL file", () => {
    const dir = mkdtempSync(join(tmpdir(), "penge-mcp-config-"));
    const target = join(dir, "database-url");
    const link = join(dir, "database-url-link");
    writeFileSync(target, new URL("postgresql://localhost/penge").toString(), { mode: 0o600 });
    symlinkSync(target, link);
    try {
      expect(() =>
        loadConfig({
          PENGE_DB_URL_FILE: link,
          PENGE_DUCKDB_PATH: "x.duckdb",
        }),
      ).toThrow(/could not be read securely/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("rejects an invalid URL", () => {
    expect(() =>
      loadConfig({
        PENGE_DB_URL: "not-a-url",
        PENGE_DUCKDB_PATH: "x.duckdb",
      }),
    ).toThrow(ConfigError);
  });

  it("rejects identity-bearing audit attribution", () => {
    expect(() =>
      loadConfig({
        PENGE_DB_URL: new URL("http://localhost").toString(),
        PENGE_DUCKDB_PATH: "x.duckdb",
        PENGE_MCP_ACTOR_ID: "person@example.com",
      }),
    ).toThrow(ConfigError);
  });

  it("rejects name-like values that are not generated ULID pseudonyms", () => {
    expect(() =>
      loadConfig({
        PENGE_DB_URL: new URL("http://localhost").toString(),
        PENGE_DUCKDB_PATH: "x.duckdb",
        PENGE_MCP_ACTOR_ID: "Rouven123",
      }),
    ).toThrow(ConfigError);
  });

  it("rejects Crockford identifiers outside the ULID timestamp range", () => {
    expect(() =>
      loadConfig({
        PENGE_DB_URL: new URL("http://localhost").toString(),
        PENGE_DUCKDB_PATH: "x.duckdb",
        PENGE_MCP_ACTOR_ID: "actor_ZZZZZZZZZZZZZZZZZZZZZZZZZZ",
      }),
    ).toThrow(ConfigError);
  });
});

import { describe, expect, it } from "vitest";

import { ConfigError, loadConfig } from "../src/config.js";

describe("loadConfig", () => {
  it("parses a valid environment", () => {
    const cfg = loadConfig({
      PENGE_DB_URL: "postgres://penge:penge@localhost:5432/penge",
      PENGE_DUCKDB_PATH: "/var/lib/penge/marts.duckdb",
    });
    expect(cfg.databaseUrl).toBe("postgres://penge:penge@localhost:5432/penge");
    expect(cfg.duckdbPath).toBe("/var/lib/penge/marts.duckdb");
    expect(cfg.logDir).toBe("logs/mcp");
  });

  it("rejects missing PENGE_DB_URL", () => {
    expect(() => loadConfig({ PENGE_DUCKDB_PATH: "x.duckdb" } as NodeJS.ProcessEnv)).toThrow(
      ConfigError,
    );
  });

  it("rejects an invalid URL", () => {
    expect(() =>
      loadConfig({
        PENGE_DB_URL: "not-a-url",
        PENGE_DUCKDB_PATH: "x.duckdb",
      }),
    ).toThrow(ConfigError);
  });
});

import { describe, expect, it } from "vitest";

import { MCP_CHAT_TOOL_ALLOWLIST, MCP_REGISTRATION_ALLOWLIST } from "../src/config.js";
import {
  assertExactMcpRegistration,
  assertMcpSourceAllowed,
  assertMcpToolAllowed,
  buildMcpServerConfig,
} from "../src/mcp.js";
import { projectEvidence } from "../src/runtime.js";
import { assertPromptIsSafe } from "../src/security.js";
import { syntheticConfig } from "./helpers.js";

describe("read-only MCP policy", () => {
  it("allows only exact contract tools and sources", () => {
    expect(() => assertMcpToolAllowed("get_source_coverage")).not.toThrow();
    expect(() => assertMcpSourceAllowed("nordnet")).not.toThrow();
    expect(() => assertMcpToolAllowed("execute_sql")).toThrow(/denied by policy/);
    expect(() => assertMcpToolAllowed("_meta")).toThrow(/not in contract/);
    expect(() => assertMcpSourceAllowed("internet")).toThrow(/source allowlist/);
  });

  it("requires the exact authoritative registration set and output schemas", () => {
    const exact = MCP_REGISTRATION_ALLOWLIST.map((name) => ({
      name,
      outputSchema: { type: "object" },
    }));
    expect(() => assertExactMcpRegistration(exact)).not.toThrow();
    expect(() => assertExactMcpRegistration(exact.slice(1))).toThrow(/missing=/);
    expect(() =>
      assertExactMcpRegistration([...exact, { name: "execute_sql", outputSchema: {} }]),
    ).toThrow(/unexpected=execute_sql/);
    expect(() => assertExactMcpRegistration(exact.map((tool) => ({ name: tool.name })))).toThrow(
      /missingOutputSchema/,
    );
  });

  it("requires exact get_source_coverage tool_allowlist equality and rejects drift", () => {
    const ok = {
      tool_allowlist: [...MCP_REGISTRATION_ALLOWLIST],
      sources: [{ id: "nordnet", coverage: { completeness: "partial", freshness: "fresh" } }],
    };
    expect(() => projectEvidence("get_source_coverage", ok)).not.toThrow();

    expect(() =>
      projectEvidence("get_source_coverage", {
        sources: ok.sources,
      }),
    ).toThrow(/structuredContent is malformed/);

    expect(() =>
      projectEvidence("get_source_coverage", {
        ...ok,
        tool_allowlist: [...MCP_CHAT_TOOL_ALLOWLIST],
      }),
    ).toThrow(/missing=_meta/);

    expect(() =>
      projectEvidence("get_source_coverage", {
        ...ok,
        tool_allowlist: [...MCP_REGISTRATION_ALLOWLIST, "execute_sql"],
      }),
    ).toThrow(/tool_allowlist differs/);

    expect(() =>
      projectEvidence("get_source_coverage", {
        ...ok,
        tool_allowlist: [...MCP_REGISTRATION_ALLOWLIST, "_meta"],
      }),
    ).toThrow(/duplicate=_meta/);

    const reordered = [...MCP_REGISTRATION_ALLOWLIST];
    [reordered[0], reordered[1]] = [reordered[1]!, reordered[0]!];
    expect(() =>
      projectEvidence("get_source_coverage", {
        ...ok,
        tool_allowlist: reordered,
      }),
    ).toThrow(/expected\[0\]=_meta/);
  });

  it("passes only mounted credential paths to the local MCP child", () => {
    const server = buildMcpServerConfig(syntheticConfig());
    expect(server.env).toMatchObject({
      PENGE_DB_URL_FILE: "/run/secrets/penge-db-url-v1",
    });
    expect(server.env).not.toHaveProperty("PENGE_DB_URL");
    expect(server).not.toHaveProperty("url");
  });

  it("does not use prompt keywords as a security boundary", () => {
    expect(() =>
      assertPromptIsSafe(
        "Show whether a shell company changed prior tax instructions in my finance records.",
      ),
    ).not.toThrow();
    expect(() => assertPromptIsSafe(" ".repeat(8_001))).toThrow(/length/);
  });
});

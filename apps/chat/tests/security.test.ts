import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";

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
  const independentlyPinnedMcpContract = [
    "_meta",
    "query_net_worth",
    "query_cashflow",
    "query_household_report",
    "search_household_transactions",
    "get_household_transaction_detail",
    "get_household_taxonomy_summary",
    "get_household_rule_summary",
    "get_household_merchant_summary",
    "get_merchant_reference_status",
    "search_merchant_reference",
    "get_source_coverage",
    "compute_tax_year",
    "run_scenario",
    "answer_planning_question",
    "search_documents",
    "suggest_import_mapping",
  ] as const;

  it("matches the independently pinned issue #350 registration sequence", () => {
    expect(MCP_REGISTRATION_ALLOWLIST).toEqual(independentlyPinnedMcpContract);
  });

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
    const server = buildMcpServerConfig(
      syntheticConfig(),
      "actor_0123456789abcdef0123456789abcdef",
      "00000000-0000-4000-8000-000000000001",
    );
    expect(server.env).toMatchObject({
      PENGE_DB_URL_FILE: "/run/secrets/penge-db-url-v1",
    });
    expect(server.env).not.toHaveProperty("PENGE_DB_URL");
    expect(server).not.toHaveProperty("url");
  });

  it("passes opaque contract-compatible audit attribution into the MCP child", () => {
    const first = buildMcpServerConfig(
      syntheticConfig(),
      "actor_0123456789abcdef0123456789abcdef",
      "00000000-0000-4000-8000-000000000001",
    );
    const second = buildMcpServerConfig(
      syntheticConfig(),
      "actor_0123456789abcdef0123456789abcdef",
      "00000000-0000-4000-8000-000000000002",
    );
    const child = spawnSync(
      process.execPath,
      [
        "-e",
        "process.stdout.write(JSON.stringify({actor:process.env.PENGE_MCP_ACTOR_ID,session:process.env.PENGE_MCP_SESSION_ID}))",
      ],
      { env: first.env, encoding: "utf8" },
    );
    expect(child.status).toBe(0);
    const attribution = JSON.parse(child.stdout) as { actor: string; session: string };
    expect(attribution.actor).toMatch(/^actor_[0-7][0-9A-HJKMNP-TV-Z]{25}$/);
    expect(attribution.session).toMatch(/^session_[0-7][0-9A-HJKMNP-TV-Z]{25}$/);
    expect(attribution.actor).toBe(second.env?.PENGE_MCP_ACTOR_ID);
    expect(attribution.session).not.toBe(second.env?.PENGE_MCP_SESSION_ID);
    expect(child.stdout).not.toContain("0123456789abcdef");
    expect(child.stdout).not.toContain("00000000-0000-4000-8000-000000000001");
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

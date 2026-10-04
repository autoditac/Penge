import { describe, expect, it } from "vitest";

import { assertMcpSourceAllowed, assertMcpToolAllowed } from "../src/mcp.js";
import { redactedArgumentKeys } from "../src/security.js";

describe("read-only MCP policy", () => {
  it("allows only exact contract tools and sources", () => {
    expect(() => assertMcpToolAllowed("get_source_coverage")).not.toThrow();
    expect(() => assertMcpSourceAllowed("nordnet")).not.toThrow();
    expect(() => assertMcpToolAllowed("execute_sql")).toThrow(/denied by policy/);
    expect(() => assertMcpToolAllowed("_meta")).toThrow(/not in contract/);
    expect(() => assertMcpSourceAllowed("internet")).toThrow(/source allowlist/);
  });

  it("audits argument names without values", () => {
    const keys = redactedArgumentKeys({
      account_id: "synthetic-secret-account",
      token: "synthetic-token",
    });
    expect(keys).toEqual(["account_id", "token"]);
    expect(JSON.stringify(keys)).not.toContain("synthetic-secret-account");
  });
});

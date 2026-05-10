import { describe, expect, it } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import type { AuditLogger } from "../src/audit.js";
import { buildServer } from "../src/server.js";

function createCollectingAudit(): AuditLogger & { entries: Array<Record<string, unknown>> } {
  const entries: Array<Record<string, unknown>> = [];
  return {
    entries,
    record(entry) {
      entries.push({ ts: new Date().toISOString(), ...entry });
    },
    async close() {
      /* noop */
    },
  };
}

async function newConnectedClient(audit: AuditLogger) {
  const { server } = buildServer({
    name: "penge-mcp-test",
    version: "0.0.0-test",
    audit,
  });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  const client = new Client(
    { name: "penge-mcp-test-client", version: "0.0.0-test" },
    { capabilities: {} },
  );
  await client.connect(clientTransport);
  return { client, server };
}

describe("MCP server skeleton", () => {
  it("starts up and lists the _meta tool", async () => {
    const audit = createCollectingAudit();
    const { client, server } = await newConnectedClient(audit);
    try {
      const list = await client.listTools();
      const names = list.tools.map((t) => t.name);
      expect(names).toContain("_meta");
      const meta = list.tools.find((t) => t.name === "_meta");
      expect(meta?.inputSchema.type).toBe("object");
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("invokes the _meta tool and returns server identity", async () => {
    const audit = createCollectingAudit();
    const { client, server } = await newConnectedClient(audit);
    try {
      const result = await client.callTool({ name: "_meta", arguments: {} });
      const content = result.content as Array<{ type: string; text: string }>;
      expect(content[0]?.type).toBe("text");
      const payload = JSON.parse(content[0]!.text) as Record<string, unknown>;
      expect(payload.serverName).toBe("penge-mcp-test");
      expect(payload.serverVersion).toBe("0.0.0-test");
      expect(payload.tools).toEqual(["_meta"]);
      expect(typeof payload.ts).toBe("string");

      expect(audit.entries).toHaveLength(1);
      expect(audit.entries[0]).toMatchObject({ tool: "_meta", status: "ok" });
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects calls to unknown tools and audits the failure", async () => {
    const audit = createCollectingAudit();
    const { client, server } = await newConnectedClient(audit);
    try {
      await expect(client.callTool({ name: "does_not_exist", arguments: {} })).rejects.toThrow();
      expect(audit.entries).toHaveLength(1);
      expect(audit.entries[0]).toMatchObject({ tool: "does_not_exist", status: "error" });
    } finally {
      await client.close();
      await server.close();
    }
  });
});

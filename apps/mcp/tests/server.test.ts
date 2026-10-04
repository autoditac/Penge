import { describe, expect, it } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { z } from "zod/v3";

import type { AuditLogger } from "../src/audit.js";
import {
  assertRegisteredToolAllowlist,
  assertSourceCatalogCoverage,
  MCP_READ_ONLY_TOOL_ALLOWLIST,
  SOURCE_CATALOG,
  type SourceCatalogEntry,
} from "../src/sources.js";
import { buildServer } from "../src/server.js";
import { getSourceCoverageTool } from "../src/tools/getSourceCoverage.js";

it("fails closed when a supported source lacks an MCP evidence path", () => {
  expect(() => assertSourceCatalogCoverage()).not.toThrow();
  const incomplete = SOURCE_CATALOG.map((source) =>
    source.id === "gls" ? ({ ...source, evidence_paths: [] } as SourceCatalogEntry) : source,
  );
  expect(() => assertSourceCatalogCoverage(incomplete)).toThrow(
    "supported source gls has no MCP evidence path",
  );
});

it("fails closed when registered tools differ from the stdio allowlist", () => {
  expect(() => assertRegisteredToolAllowlist(MCP_READ_ONLY_TOOL_ALLOWLIST)).not.toThrow();
  expect(() => assertRegisteredToolAllowlist(["_meta", "mutate_everything"])).toThrow(
    "registered MCP tools differ from the read-only allowlist",
  );
});

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
      expect(meta?.outputSchema?.type).toBe("object");
      expect(meta?.outputSchema?.required).toContain("serverName");
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
      expect(result.structuredContent).toEqual(payload);

      expect(audit.entries).toHaveLength(1);
      expect(audit.entries[0]).toMatchObject({ tool: "_meta", status: "ok" });
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("publishes output schemas and structured content for object and array tools", async () => {
    const audit = createCollectingAudit();
    const objectTool = {
      name: "source_evidence",
      description: "Synthetic object evidence.",
      inputSchema: z.object({}).strict(),
      outputSchema: z.object({ source: z.literal("gls"), freshness: z.literal("fresh") }).strict(),
      handler: () => ({ source: "gls" as const, freshness: "fresh" as const }),
    };
    const arrayTool = {
      name: "source_values",
      description: "Synthetic array evidence.",
      inputSchema: z.object({}).strict(),
      outputSchema: z.array(z.object({ currency: z.literal("EUR"), summary: z.string() }).strict()),
      handler: () => [{ currency: "EUR" as const, summary: "synthetic" }],
    };
    const { server } = buildServer({
      name: "penge-mcp-test",
      version: "0.0.0-test",
      audit,
      extraTools: [objectTool, arrayTool],
    });
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    const client = new Client(
      { name: "penge-mcp-test-client", version: "0.0.0-test" },
      { capabilities: {} },
    );
    await client.connect(clientTransport);
    try {
      const tools = await client.listTools();
      expect(tools.tools.every((tool) => tool.outputSchema !== undefined)).toBe(true);
      const objectDefinition = tools.tools.find((tool) => tool.name === objectTool.name);
      expect(objectDefinition?.outputSchema).toMatchObject({
        type: "object",
        required: ["source", "freshness"],
      });

      const arrayDefinition = tools.tools.find((tool) => tool.name === arrayTool.name);
      expect(arrayDefinition?.outputSchema).toMatchObject({
        type: "object",
        required: ["result"],
      });

      const objectResult = await client.callTool({ name: objectTool.name, arguments: {} });
      expect(objectResult.structuredContent).toEqual({ source: "gls", freshness: "fresh" });
      const arrayResult = await client.callTool({ name: arrayTool.name, arguments: {} });
      expect(arrayResult.structuredContent).toEqual({
        result: [{ currency: "EUR", summary: "synthetic" }],
      });
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("exposes source coverage schema and typed evidence as structured content", async () => {
    const audit = createCollectingAudit();
    const coverageTool = getSourceCoverageTool({
      runner: {
        async query() {
          return { rows: [] };
        },
      },
      now: () => new Date("2026-10-04T08:00:00.000Z"),
    });
    const { server } = buildServer({
      name: "penge-mcp-test",
      version: "0.0.0-test",
      audit,
      extraTools: [coverageTool],
    });
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    const client = new Client(
      { name: "penge-mcp-test-client", version: "0.0.0-test" },
      { capabilities: {} },
    );
    await client.connect(clientTransport);
    try {
      const listed = await client.listTools();
      const coverageDefinition = listed.tools.find((tool) => tool.name === coverageTool.name);
      expect(coverageDefinition?.outputSchema).toMatchObject({
        type: "object",
        required: expect.arrayContaining([
          "generated_at",
          "source_allowlist",
          "tool_allowlist",
          "sources",
          "complete",
        ]),
      });

      const result = await client.callTool({
        name: coverageTool.name,
        arguments: { source_ids: ["ecb_fx"] },
      });
      expect(result.structuredContent).toMatchObject({
        transport: "stdio",
        read_only: true,
        complete: false,
        sources: [
          {
            id: "ecb_fx",
            coverage: { completeness: "missing", freshness: "unknown" },
          },
        ],
      });
      const text = result.content[0];
      expect(text?.type).toBe("text");
      if (text?.type !== "text") throw new Error("source coverage text content is missing");
      expect(JSON.parse(text.text)).toEqual(result.structuredContent);
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

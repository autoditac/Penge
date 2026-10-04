#!/usr/bin/env node
/**
 * Penge MCP server entrypoint. Speaks JSON-RPC over stdio so it can be
 * launched directly by MCP hosts (Claude Desktop, VS Code Copilot Chat, etc.).
 */

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createAuditLogger } from "./audit.js";
import { loadConfig } from "./config.js";
import { connect } from "./db.js";
import { buildServer } from "./server.js";
import { assertRegisteredToolAllowlist, assertSourceCatalogCoverage } from "./sources.js";
import { answerPlanningQuestionTool } from "./tools/answerPlanningQuestion.js";
import { computeTaxYearTool } from "./tools/computeTaxYear.js";
import { getHouseholdMerchantSummaryTool } from "./tools/getHouseholdMerchantSummary.js";
import { getHouseholdRuleSummaryTool } from "./tools/getHouseholdRuleSummary.js";
import { getHouseholdTaxonomySummaryTool } from "./tools/getHouseholdTaxonomySummary.js";
import { getHouseholdTransactionDetailTool } from "./tools/getHouseholdTransactionDetail.js";
import { getMerchantReferenceStatusTool } from "./tools/getMerchantReferenceStatus.js";
import { getSourceCoverageTool } from "./tools/getSourceCoverage.js";
import { queryCashflowTool } from "./tools/queryCashflow.js";
import { queryHouseholdReportTool } from "./tools/queryHouseholdReport.js";
import { queryNetWorthTool } from "./tools/queryNetWorth.js";
import { runScenarioTool } from "./tools/runScenario.js";
import { searchDocumentsTool } from "./tools/searchDocuments.js";
import { searchHouseholdTransactionsTool } from "./tools/searchHouseholdTransactions.js";
import { searchMerchantReferenceTool } from "./tools/searchMerchantReference.js";
import { suggestImportMappingTool } from "./tools/suggestImportMapping.js";

const SERVER_NAME = "penge-mcp";
const SERVER_VERSION = "0.0.0";

async function main(): Promise<void> {
  const config = loadConfig();
  const audit = createAuditLogger({
    logDir: config.logDir,
    ...(config.actorId === undefined ? {} : { actorId: config.actorId }),
    ...(config.sessionId === undefined ? {} : { sessionId: config.sessionId }),
  });
  const data = await connect({
    databaseUrl: config.databaseUrl,
    duckdbPath: config.duckdbPath,
  });

  const { server, registry } = buildServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
    audit,
    extraTools: [
      queryNetWorthTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      queryCashflowTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      queryHouseholdReportTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      searchHouseholdTransactionsTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      getHouseholdTransactionDetailTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      getHouseholdTaxonomySummaryTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      getHouseholdRuleSummaryTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      getHouseholdMerchantSummaryTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      getMerchantReferenceStatusTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      searchMerchantReferenceTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      getSourceCoverageTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      computeTaxYearTool(),
      runScenarioTool(),
      answerPlanningQuestionTool(),
      searchDocumentsTool({ vaultRoot: config.vaultRoot }),
      suggestImportMappingTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
    ],
  });
  assertSourceCatalogCoverage();
  assertRegisteredToolAllowlist(registry.list().map((tool) => tool.name));

  const transport = new StdioServerTransport();
  await server.connect(transport);

  const shutdown = async (): Promise<void> => {
    try {
      await server.close();
    } finally {
      await data.close();
      await audit.close();
    }
  };

  process.on("SIGINT", () => {
    void shutdown().then(() => process.exit(0));
  });
  process.on("SIGTERM", () => {
    void shutdown().then(() => process.exit(0));
  });
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});

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
import type { HouseholdTransactionQueryRunner } from "./tools/searchHouseholdTransactions.js";

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
  const runner: HouseholdTransactionQueryRunner = {
    async query(sql, params) {
      const client = await data.acquire();
      try {
        return await client.query(sql, [...params]);
      } finally {
        client.release();
      }
    },
  };
  const snapshotRunner = {
    ...runner,
    async readSnapshot<T>(
      operation: (transactionRunner: HouseholdTransactionQueryRunner) => Promise<T>,
    ): Promise<T> {
      const client = await data.acquire();
      let transactionStarted = false;
      try {
        await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
        transactionStarted = true;
        const transactionRunner: HouseholdTransactionQueryRunner = {
          async query(sql, params) {
            return await client.query(sql, [...params]);
          },
        };
        const result = await operation(transactionRunner);
        await client.query("COMMIT");
        return result;
      } catch (error) {
        if (transactionStarted) await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    },
  };

  const { server, registry } = buildServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
    audit,
    extraTools: [
      queryNetWorthTool({
        runner,
      }),
      queryCashflowTool({
        runner,
      }),
      queryHouseholdReportTool({
        runner,
      }),
      searchHouseholdTransactionsTool({
        runner,
      }),
      getHouseholdTransactionDetailTool({
        runner: snapshotRunner,
      }),
      getHouseholdTaxonomySummaryTool({
        runner,
      }),
      getHouseholdRuleSummaryTool({
        runner,
      }),
      getHouseholdMerchantSummaryTool({
        runner,
      }),
      getMerchantReferenceStatusTool({
        runner,
      }),
      searchMerchantReferenceTool({
        runner,
      }),
      getSourceCoverageTool({
        runner,
      }),
      computeTaxYearTool(),
      runScenarioTool(),
      answerPlanningQuestionTool(),
      searchDocumentsTool({ vaultRoot: config.vaultRoot }),
      suggestImportMappingTool({
        runner,
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

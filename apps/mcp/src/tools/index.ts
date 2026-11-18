import { answerPlanningQuestionTool } from "./answerPlanningQuestion.js";
import { computeTaxYearTool } from "./computeTaxYear.js";
import { getHouseholdMerchantSummaryTool } from "./getHouseholdMerchantSummary.js";
import { getHouseholdRuleSummaryTool } from "./getHouseholdRuleSummary.js";
import { getHouseholdTaxonomySummaryTool } from "./getHouseholdTaxonomySummary.js";
import { getHouseholdTransactionDetailTool } from "./getHouseholdTransactionDetail.js";
import { getMerchantReferenceStatusTool } from "./getMerchantReferenceStatus.js";
import { getSourceCoverageTool } from "./getSourceCoverage.js";
import { queryCashflowTool } from "./queryCashflow.js";
import { queryHouseholdReportTool } from "./queryHouseholdReport.js";
import { queryNetWorthTool } from "./queryNetWorth.js";
import { runScenarioTool } from "./runScenario.js";
import { searchDocumentsTool } from "./searchDocuments.js";
import { searchHouseholdTransactionsTool } from "./searchHouseholdTransactions.js";
import type { HouseholdTransactionQueryRunner } from "./searchHouseholdTransactions.js";
import { searchMerchantReferenceTool } from "./searchMerchantReference.js";
import { suggestImportMappingTool } from "./suggestImportMapping.js";

export interface PengeQueryRunner extends HouseholdTransactionQueryRunner {
  readSnapshot<T>(operation: (runner: HouseholdTransactionQueryRunner) => Promise<T>): Promise<T>;
}

export interface PengeToolOptions {
  runner: PengeQueryRunner;
  vaultRoot: string;
}

export function createPengeTools(options: PengeToolOptions) {
  return [
    queryNetWorthTool({ runner: options.runner }),
    queryCashflowTool({ runner: options.runner }),
    queryHouseholdReportTool({ runner: options.runner }),
    searchHouseholdTransactionsTool({ runner: options.runner }),
    getHouseholdTransactionDetailTool({ runner: options.runner }),
    getHouseholdTaxonomySummaryTool({ runner: options.runner }),
    getHouseholdRuleSummaryTool({ runner: options.runner }),
    getHouseholdMerchantSummaryTool({ runner: options.runner }),
    getMerchantReferenceStatusTool({ runner: options.runner }),
    searchMerchantReferenceTool({ runner: options.runner }),
    getSourceCoverageTool({ runner: options.runner }),
    computeTaxYearTool(),
    runScenarioTool(),
    answerPlanningQuestionTool(),
    searchDocumentsTool({ vaultRoot: options.vaultRoot }),
    suggestImportMappingTool({ runner: options.runner }),
  ];
}

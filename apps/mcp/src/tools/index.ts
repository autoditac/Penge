import { answerPlanningQuestionTool } from "./answerPlanningQuestion.js";
import { computeTaxYearTool } from "./computeTaxYear.js";
import { queryCashflowTool } from "./queryCashflow.js";
import { queryHouseholdReportTool } from "./queryHouseholdReport.js";
import { queryNetWorthTool } from "./queryNetWorth.js";
import { runScenarioTool } from "./runScenario.js";
import { searchDocumentsTool } from "./searchDocuments.js";
import { suggestImportMappingTool } from "./suggestImportMapping.js";

export interface PengeQueryRunner {
  query<R extends Record<string, unknown>>(
    sql: string,
    params: ReadonlyArray<unknown>,
  ): Promise<{ rows: R[] }>;
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
    computeTaxYearTool(),
    runScenarioTool(),
    answerPlanningQuestionTool(),
    searchDocumentsTool({ vaultRoot: options.vaultRoot }),
    suggestImportMappingTool({ runner: options.runner }),
  ];
}

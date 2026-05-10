/**
 * Golden questions for the MCP eval harness.
 *
 * Twenty deterministic, fixture-backed checks of the MCP tool layer.
 * Each golden wires synthetic data into the actual tool handler and
 * asserts an invariant or exact numeric expectation. None of the
 * goldens go through an LLM — the host pipeline is exercised end-to-
 * end inside the TypeScript MCP server only.
 *
 * To add a new golden, see `docs/mcp/evals.md`.
 */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { queryNetWorthTool, type NetWorthQueryRunner } from "../src/tools/queryNetWorth.js";
import { queryCashflowTool, type CashflowQueryRunner } from "../src/tools/queryCashflow.js";
import { computeTaxYearTool, type SubprocessRunner } from "../src/tools/computeTaxYear.js";
import {
  runScenarioTool,
  type BaselineLoader,
  type ScenarioSubprocessRunner,
} from "../src/tools/runScenario.js";
import { searchDocumentsTool } from "../src/tools/searchDocuments.js";

import {
  approxEqual,
  expectFiniteNonNegative,
  expectNoRawAccountLeak,
  expectPercentileOrdering,
  expectSumCloseTo,
} from "./assertions.js";
import {
  NW_BY_ACCOUNT_EUR,
  NW_BY_ASSET_CLASS_EUR,
  NW_DATE,
  NW_FX_EUR_PER_DKK,
  NW_TOTAL_DKK,
  NW_TOTAL_EUR,
} from "./fixtures/netWorthRows.js";
import {
  CF_DAILY_EUR,
  CF_DAILY_NET_EUR,
  CF_DAYS_IN_MONTH,
  CF_MONTHLY_DKK,
  CF_MONTHLY_EUR,
  CF_RANGE,
  CF_YEARLY_EUR,
} from "./fixtures/cashflowRows.js";
import {
  AKS_RATE,
  DE_MIXED_EUR,
  DE_VORAB_BASE_EUR,
  DK_AKS_DKK,
  DK_CARRY_DKK,
  DK_FULL_DKK,
  DK_LAGER_EUR,
  DK_PAL_DKK,
  NORDNET_LAGER_GAIN_DKK,
  NORDNET_LAGER_TAX_RATE,
  PAL_EXPECTED_TAX_DKK,
  PAL_RATE,
  VORAB_BASE_NAV_EUR,
  VORAB_BASE_RATE,
  VORAB_EQUITY_TAXABLE_FRACTION,
} from "./fixtures/taxPayloads.js";
import {
  BASELINE_MC_PAYLOAD,
  FAKE_BASELINE_SPEC,
  HOUSE_PURCHASE_PAYLOAD,
  WORK_REDUCTION_PAYLOAD,
} from "./fixtures/scenarioPayloads.js";
import { SYNTHETIC_VAULT_DOCS, buildVault } from "./fixtures/vaultDocs.js";

const CTX = { serverName: "evals", serverVersion: "0.0.0-evals" };

export type ToolName =
  | "query_net_worth"
  | "query_cashflow"
  | "compute_tax_year"
  | "run_scenario"
  | "search_documents";

export interface Golden {
  /** Stable, kebab-case id used to refer to the question in CI logs. */
  id: string;
  /** The human-readable question this golden documents. */
  question: string;
  /** Why the invariant matters — one sentence is enough. */
  rationale: string;
  /** Tool exercised by the golden (informational; the runner does not switch on it). */
  tool: ToolName;
  /** Executes the golden. Throws on failure with a contextual message. */
  run: () => Promise<void>;
}

// --- Helpers ---------------------------------------------------------

/**
 * Build a fake net-worth runner that returns pre-canned rows for each
 * sequential `query` call. The harness pushes one entry per expected
 * call in the order they will be made.
 */
function queuedNetWorthRunner(
  queue: ReadonlyArray<
    ReadonlyArray<{ date: string; breakdown_key: string | null; value: number }>
  >,
): NetWorthQueryRunner {
  let i = 0;
  return {
    async query() {
      const rows = queue[i] ?? [];
      i += 1;
      return { rows: rows as never };
    },
  };
}

function queuedCashflowRunner(
  queue: ReadonlyArray<
    ReadonlyArray<{
      period_start: string;
      period_end: string;
      inflow: number;
      outflow: number;
      net: number;
    }>
  >,
): CashflowQueryRunner {
  let i = 0;
  return {
    async query() {
      const rows = queue[i] ?? [];
      i += 1;
      return { rows: rows as never };
    },
  };
}

function fixedRunner<T>(payload: T): SubprocessRunner {
  return {
    async run() {
      return payload;
    },
  };
}

function fixedScenarioRunner(payload: unknown): ScenarioSubprocessRunner {
  return {
    async run() {
      return payload;
    },
  };
}

function fakeBaselineLoader(): BaselineLoader {
  return { load: () => structuredClone(FAKE_BASELINE_SPEC) };
}

// --- Goldens ---------------------------------------------------------

export const GOLDENS: Golden[] = [
  // ===== Net worth (3) ===============================================
  {
    id: "nw-sum-accounts-equals-total",
    question: "Does the sum of per-account net worth on 2024-01-31 equal the household total?",
    rationale:
      "Per-account breakdown must reconcile to the no-breakdown total. A drift here means the mart is double-counting or dropping accounts.",
    tool: "query_net_worth",
    async run() {
      const runner = queuedNetWorthRunner([NW_TOTAL_EUR, NW_BY_ACCOUNT_EUR]);
      const tool = queryNetWorthTool({ runner });
      const total = await tool.handler(
        {
          date_range: { from: NW_DATE, to: NW_DATE },
          currency: "EUR",
          breakdown_by: "none",
        },
        CTX,
      );
      const byAccount = await tool.handler(
        {
          date_range: { from: NW_DATE, to: NW_DATE },
          currency: "EUR",
          breakdown_by: "account",
        },
        CTX,
      );
      tool.outputSchema.parse(total);
      tool.outputSchema.parse(byAccount);
      const totalValue = total[0]?.value ?? 0;
      expectSumCloseTo(
        byAccount.map((r) => r.value),
        totalValue,
        0.0001,
        "sum(per-account) vs total",
      );
    },
  },
  {
    id: "nw-asset-class-rolls-up",
    question: "Does breakdown_by='asset_class' sum to the no-breakdown total on the same date?",
    rationale:
      "Asset-class rollup is the basis for allocation tables in the FIRE planner. The dimensions must be a partition.",
    tool: "query_net_worth",
    async run() {
      const runner = queuedNetWorthRunner([NW_TOTAL_EUR, NW_BY_ASSET_CLASS_EUR]);
      const tool = queryNetWorthTool({ runner });
      const total = await tool.handler(
        { date_range: { from: NW_DATE, to: NW_DATE }, currency: "EUR", breakdown_by: "none" },
        CTX,
      );
      const byClass = await tool.handler(
        {
          date_range: { from: NW_DATE, to: NW_DATE },
          currency: "EUR",
          breakdown_by: "asset_class",
        },
        CTX,
      );
      expectSumCloseTo(
        byClass.map((r) => r.value),
        total[0]?.value ?? 0,
        0.0001,
        "sum(asset_class) vs total",
      );
    },
  },
  {
    id: "nw-cross-currency-parity",
    question: "Are EUR and DKK net-worth totals consistent under the fixed FX rate (within 0.5 %)?",
    rationale:
      "EUR and DKK are both first-class in Penge; the mart must produce numerically consistent values in both.",
    tool: "query_net_worth",
    async run() {
      const runner = queuedNetWorthRunner([NW_TOTAL_EUR, NW_TOTAL_DKK]);
      const tool = queryNetWorthTool({ runner });
      const eur = await tool.handler(
        { date_range: { from: NW_DATE, to: NW_DATE }, currency: "EUR", breakdown_by: "none" },
        CTX,
      );
      const dkk = await tool.handler(
        { date_range: { from: NW_DATE, to: NW_DATE }, currency: "DKK", breakdown_by: "none" },
        CTX,
      );
      const eurValue = eur[0]?.value ?? 0;
      const dkkValue = dkk[0]?.value ?? 0;
      approxEqual(dkkValue * NW_FX_EUR_PER_DKK, eurValue, 0.005, "DKK→EUR parity");
    },
  },

  // ===== Cashflow (3) ================================================
  {
    id: "cf-monthly-matches-sum-of-daily",
    question: "Does the monthly aggregation for Jan 2024 equal the sum of daily rows?",
    rationale:
      "Granularity rollups must be conservative. If the month bucket disagrees with the daily sum, downstream FIRE projections see the wrong cashflow.",
    tool: "query_cashflow",
    async run() {
      const runner = queuedCashflowRunner([CF_DAILY_EUR, CF_MONTHLY_EUR]);
      const tool = queryCashflowTool({ runner });
      const daily = await tool.handler(
        {
          date_range: { from: CF_RANGE.from, to: CF_RANGE.to },
          granularity: "day",
          currency: "EUR",
        },
        CTX,
      );
      const monthly = await tool.handler(
        {
          date_range: { from: CF_RANGE.from, to: CF_RANGE.to },
          granularity: "month",
          currency: "EUR",
        },
        CTX,
      );
      const dailyNet = daily.reduce((acc, r) => acc + r.net, 0);
      const monthlyNet = monthly.reduce((acc, r) => acc + r.net, 0);
      approxEqual(monthlyNet, dailyNet, 0.0001, "monthly net vs daily-sum net");
      // Sanity: matches the fixture-derived expectation as well.
      approxEqual(
        monthlyNet,
        CF_DAILY_NET_EUR * CF_DAYS_IN_MONTH,
        0.0001,
        "monthly net vs fixture total",
      );
    },
  },
  {
    id: "cf-rollup-invariant-month-vs-year",
    question: "Does year-granularity equal month-granularity for a single-month range?",
    rationale:
      "Different granularities applied to the same window must collapse to the same net total — a basic conservation check.",
    tool: "query_cashflow",
    async run() {
      const runner = queuedCashflowRunner([CF_MONTHLY_EUR, CF_YEARLY_EUR]);
      const tool = queryCashflowTool({ runner });
      const monthly = await tool.handler(
        {
          date_range: { from: CF_RANGE.from, to: CF_RANGE.to },
          granularity: "month",
          currency: "EUR",
        },
        CTX,
      );
      const yearly = await tool.handler(
        {
          date_range: { from: CF_RANGE.from, to: CF_RANGE.to },
          granularity: "year",
          currency: "EUR",
        },
        CTX,
      );
      const mNet = monthly.reduce((acc, r) => acc + r.net, 0);
      const yNet = yearly.reduce((acc, r) => acc + r.net, 0);
      approxEqual(yNet, mNet, 0.0001, "year vs month total");
    },
  },
  {
    id: "cf-currency-preserves-net-sign",
    question: "Does cashflow net keep its sign across EUR and DKK conversions?",
    rationale:
      "Currency choice must never flip a surplus into a deficit. Sign preservation is the cheapest sanity check.",
    tool: "query_cashflow",
    async run() {
      const runner = queuedCashflowRunner([CF_MONTHLY_EUR, CF_MONTHLY_DKK]);
      const tool = queryCashflowTool({ runner });
      const eur = await tool.handler(
        {
          date_range: { from: CF_RANGE.from, to: CF_RANGE.to },
          granularity: "month",
          currency: "EUR",
        },
        CTX,
      );
      const dkk = await tool.handler(
        {
          date_range: { from: CF_RANGE.from, to: CF_RANGE.to },
          granularity: "month",
          currency: "DKK",
        },
        CTX,
      );
      if (Math.sign(eur[0]?.net ?? 0) !== Math.sign(dkk[0]?.net ?? 0)) {
        throw new Error(
          `EUR net sign ${Math.sign(eur[0]?.net ?? 0)} ≠ DKK net sign ${Math.sign(dkk[0]?.net ?? 0)}`,
        );
      }
    },
  },

  // ===== DK tax (5) ==================================================
  {
    id: "dk-lager-mark-to-market",
    question: "Does the DK lager line item equal the synthetic ETF mark-to-market gain?",
    rationale:
      "Lagerbeskatning is the dominant DK ETF regime; the line-item amount must equal the NAV-delta times shares for a single-position synthetic.",
    tool: "compute_tax_year",
    async run() {
      const tool = computeTaxYearTool({ runner: fixedRunner(DK_LAGER_EUR) });
      const out = await tool.handler({ year: 2024, jurisdictions: ["DK"], currency: "EUR" }, CTX);
      tool.outputSchema.parse(out);
      const lager = out[0]?.line_items.filter((li) => li.category === "lager") ?? [];
      if (lager.length === 0) {
        throw new Error("expected at least one DK lager line item, got none");
      }
      // 1000 DKK gain in EUR at ~0.13405 ≈ 134.05.
      approxEqual(lager[0]!.amount, 134.05, 0.005, "lager line-item amount (EUR)");
    },
  },
  {
    id: "dk-ask-taxable-yield",
    question: "Does the DK Aktiesparekonto line item carry the expected taxable yield (17 %)?",
    rationale:
      "AKS yield is taxed at a flat 17 %; the report should expose the gross taxable amount so the rate is auditable.",
    tool: "compute_tax_year",
    async run() {
      const tool = computeTaxYearTool({ runner: fixedRunner(DK_AKS_DKK) });
      const out = await tool.handler({ year: 2024, jurisdictions: ["DK"], currency: "DKK" }, CTX);
      const ask = out[0]?.line_items.find((li) => li.category === "ask");
      if (!ask) throw new Error("expected an `ask` line item");
      approxEqual(ask.amount, 2_000, 0.0001, "AKS gross taxable income (DKK)");
      // Implied tax-due at 17 % is 340 DKK; the report doesn't surface it
      // as its own line for AKS, but the rate must round-trip exactly.
      approxEqual(ask.amount * AKS_RATE, 340, 0.0001, "AKS implied tax @ 17 %");
    },
  },
  {
    id: "dk-pal-skat-rate",
    question: "Does PAL-skat equal 15.3 % of the synthetic pension return?",
    rationale:
      "PAL-skat is a hard-coded statutory rate; if Penge ever drifts from 15.3 %, the household's pension tax filing is wrong.",
    tool: "compute_tax_year",
    async run() {
      const tool = computeTaxYearTool({ runner: fixedRunner(DK_PAL_DKK) });
      const out = await tool.handler({ year: 2024, jurisdictions: ["DK"], currency: "DKK" }, CTX);
      const palWithheld = out[0]?.line_items.find((li) => li.category === "pal_tax_withheld");
      if (!palWithheld) throw new Error("expected a `pal_tax_withheld` line item");
      approxEqual(palWithheld.amount, PAL_EXPECTED_TAX_DKK, 0.0001, "PAL tax withheld (DKK)");
      // Cross-check the rate explicitly.
      const palGross = out[0]?.line_items.find((li) => li.category === "pal");
      if (!palGross) throw new Error("expected a `pal` line item");
      approxEqual(palWithheld.amount / palGross.amount, PAL_RATE, 0.001, "PAL effective rate");
    },
  },
  {
    id: "dk-summary-matches-line-items",
    question: "Does the DK årsopgørelse-style summary equal the sum of the underlying line items?",
    rationale:
      "Skat's årsopgørelse expects the totals on the cover sheet to equal the sum of the supporting rows. Drift here is an auditable error.",
    tool: "compute_tax_year",
    async run() {
      const tool = computeTaxYearTool({ runner: fixedRunner(DK_FULL_DKK) });
      const out = await tool.handler({ year: 2024, jurisdictions: ["DK"], currency: "DKK" }, CTX);
      const report = out[0];
      if (!report) throw new Error("expected one DK report");
      // gross_capital_income should equal the sum of taxable-gain line items.
      const taxableCategories = new Set(["lager", "ask", "realised"]);
      const gainsSum = report.line_items
        .filter((li) => taxableCategories.has(li.category))
        .reduce((acc, li) => acc + li.amount, 0);
      approxEqual(
        report.summary["gross_capital_income"] ?? 0,
        gainsSum,
        0.0001,
        "summary.gross_capital_income vs Σ line_items",
      );
    },
  },
  {
    id: "dk-loss-carry-forward",
    question: "Does a prior-year loss reduce this year's taxable_capital_income?",
    rationale:
      "DK allows capital losses to offset future capital income. The carry-forward must show up in the summary, not just in the rationale.",
    tool: "compute_tax_year",
    async run() {
      const tool = computeTaxYearTool({ runner: fixedRunner(DK_CARRY_DKK) });
      const out = await tool.handler({ year: 2024, jurisdictions: ["DK"], currency: "DKK" }, CTX);
      const summary = out[0]?.summary ?? {};
      const gross = summary["gross_capital_income"] ?? 0;
      const taxable = summary["taxable_capital_income"] ?? 0;
      const prior = summary["prior_loss_carry_forward"] ?? 0;
      if (!(prior > 0)) {
        throw new Error(`expected positive prior_loss_carry_forward, got ${prior}`);
      }
      if (!(taxable < gross)) {
        throw new Error(
          `expected taxable_capital_income (${taxable}) < gross_capital_income (${gross})`,
        );
      }
      approxEqual(gross - taxable, prior, 0.0001, "gross - taxable vs prior loss");
      // Sanity: an effective tax saving of prior * 27 % vs the no-carry case.
      const expectedSaving = prior * NORDNET_LAGER_TAX_RATE;
      if (!(expectedSaving > 0)) throw new Error("expected positive tax saving");
      if (gross !== NORDNET_LAGER_GAIN_DKK) {
        throw new Error(
          `fixture mismatch: gross_capital_income ${gross} ≠ NORDNET_LAGER_GAIN_DKK ${NORDNET_LAGER_GAIN_DKK}`,
        );
      }
    },
  },

  // ===== DE tax (3) ==================================================
  {
    id: "de-vorab-base-computation",
    question: "Does the German Vorabpauschale line item equal Basiszins × NAV?",
    rationale:
      "The Vorabpauschale base is mechanically `Basiszins × NAV`. A drift signals the tax-CLI changed the formula or the synthetic Basiszins.",
    tool: "compute_tax_year",
    async run() {
      const tool = computeTaxYearTool({ runner: fixedRunner(DE_VORAB_BASE_EUR) });
      const out = await tool.handler({ year: 2024, jurisdictions: ["DE"], currency: "EUR" }, CTX);
      const vorab = out[0]?.line_items.find((li) => li.category === "vorabpauschale");
      if (!vorab) throw new Error("expected a `vorabpauschale` line item");
      approxEqual(
        vorab.amount,
        VORAB_BASE_NAV_EUR * VORAB_BASE_RATE,
        0.0001,
        "vorabpauschale base computation",
      );
    },
  },
  {
    id: "de-teilfreistellung-equity",
    question: "Does Teilfreistellung leave 30 % of an equity-fund Vorabpauschale taxable?",
    rationale:
      "70 % Teilfreistellung is the rate for an Aktienfonds; only 30 % of the Vorabpauschale is taxable. A drift in this ratio leaks tax to the household.",
    tool: "compute_tax_year",
    async run() {
      const tool = computeTaxYearTool({ runner: fixedRunner(DE_VORAB_BASE_EUR) });
      const out = await tool.handler({ year: 2024, jurisdictions: ["DE"], currency: "EUR" }, CTX);
      const lineItems = out[0]?.line_items ?? [];
      const vorab = lineItems.find((li) => li.category === "vorabpauschale");
      const taxable = lineItems.find((li) => li.category === "vorab_taxable");
      if (!vorab || !taxable) throw new Error("expected vorabpauschale + vorab_taxable line items");
      approxEqual(
        taxable.amount,
        vorab.amount * VORAB_EQUITY_TAXABLE_FRACTION,
        0.01,
        "Teilfreistellung 70 % (taxable = 30 % of vorab)",
      );
    },
  },
  {
    id: "de-mixed-depot-line-items",
    question: "Does a mixed depot return every Vorabpauschale category for every fund?",
    rationale:
      "A depot with N funds must surface 3 × N line items (vorabpauschale / vorab_taxable / vorab_tax_due). Missing rows hide tax liability.",
    tool: "compute_tax_year",
    async run() {
      const tool = computeTaxYearTool({ runner: fixedRunner(DE_MIXED_EUR) });
      const out = await tool.handler({ year: 2024, jurisdictions: ["DE"], currency: "EUR" }, CTX);
      const lineItems = out[0]?.line_items ?? [];
      const sources = new Set(lineItems.map((li) => li.source));
      if (sources.size < 2) {
        throw new Error(`expected ≥ 2 distinct fund sources, got ${sources.size}`);
      }
      for (const source of sources) {
        for (const category of ["vorabpauschale", "vorab_taxable", "vorab_tax_due"]) {
          const found = lineItems.find((li) => li.category === category && li.source === source);
          if (!found) {
            throw new Error(`missing line item for fund ${source}, category ${category}`);
          }
          expectFiniteNonNegative(found.amount, `line ${category}@${source}`);
        }
      }
    },
  },

  // ===== FIRE / sim (4) ==============================================
  {
    id: "sim-percentile-ordering",
    question: "Do p10 ≤ p50 ≤ p90 hold for every year on baseline and scenario summaries?",
    rationale:
      "Percentile inversion would mean the Monte-Carlo summary is corrupted — every downstream FIRE conclusion would be wrong.",
    tool: "run_scenario",
    async run() {
      const tool = runScenarioTool({
        runner: fixedScenarioRunner(WORK_REDUCTION_PAYLOAD),
        baselineLoader: fakeBaselineLoader(),
      });
      const out = await tool.handler(
        {
          scenario_type: "work_reduction",
          params: { entity: "person_dk", year: 2027, fte_fraction: 0.8 },
          monte_carlo: { paths: 100, seed: 42, horizon_years: 16 },
        },
        CTX,
      );
      expectPercentileOrdering(out.baseline, "baseline");
      expectPercentileOrdering(out.scenario, "scenario");
    },
  },
  {
    id: "sim-work-reduction-shifts-fire-later",
    question: "Does cutting hours shift the median FIRE year later (positive shift)?",
    rationale:
      "Less income = lower portfolio growth = later FIRE. The sign of the FIRE-year shift is a coarse but unambiguous sanity check.",
    tool: "run_scenario",
    async run() {
      const tool = runScenarioTool({
        runner: fixedScenarioRunner(WORK_REDUCTION_PAYLOAD),
        baselineLoader: fakeBaselineLoader(),
      });
      const out = await tool.handler(
        {
          scenario_type: "work_reduction",
          params: { entity: "person_dk", year: 2027, fte_fraction: 0.7 },
          monte_carlo: { paths: 100, seed: 42, horizon_years: 16 },
        },
        CTX,
      );
      const shift = out.deltas.fire_year_shift_years;
      if (shift === null || shift <= 0) {
        throw new Error(`expected fire_year_shift_years > 0, got ${shift}`);
      }
    },
  },
  {
    id: "sim-house-purchase-shifts-fire-not-earlier",
    question: "Does a house purchase keep the median FIRE year no earlier than baseline?",
    rationale:
      "A large lump-sum outflow can only delay or leave FIRE unchanged in the Penge model; an earlier FIRE would be a logic bug.",
    tool: "run_scenario",
    async run() {
      const tool = runScenarioTool({
        runner: fixedScenarioRunner(HOUSE_PURCHASE_PAYLOAD),
        baselineLoader: fakeBaselineLoader(),
      });
      const out = await tool.handler(
        {
          scenario_type: "house_purchase",
          params: {
            year: 2028,
            price_eur: 400_000,
            downpayment_eur: 80_000,
            mortgage_rate: 0.03,
            term_years: 25,
          },
          monte_carlo: { paths: 100, seed: 42, horizon_years: 16 },
        },
        CTX,
      );
      const shift = out.deltas.fire_year_shift_years;
      if (shift === null || shift < 0) {
        throw new Error(`expected fire_year_shift_years >= 0, got ${shift}`);
      }
    },
  },
  {
    id: "sim-fixed-seed-deterministic",
    question: "Do two runs with identical inputs and seed produce identical outputs?",
    rationale:
      "Reproducibility is a hard rule: a fixed seed must produce byte-identical Monte-Carlo summaries.",
    tool: "run_scenario",
    async run() {
      const input = {
        scenario_type: "work_reduction" as const,
        params: { entity: "person_dk", year: 2027, fte_fraction: 0.9 },
        monte_carlo: { paths: 50, seed: 1234, horizon_years: 10 },
      };
      const tool1 = runScenarioTool({
        runner: fixedScenarioRunner(BASELINE_MC_PAYLOAD),
        baselineLoader: fakeBaselineLoader(),
      });
      const tool2 = runScenarioTool({
        runner: fixedScenarioRunner(BASELINE_MC_PAYLOAD),
        baselineLoader: fakeBaselineLoader(),
      });
      const out1 = await tool1.handler(input, CTX);
      const out2 = await tool2.handler(input, CTX);
      if (JSON.stringify(out1) !== JSON.stringify(out2)) {
        throw new Error("same-seed runs produced different outputs");
      }
    },
  },

  // ===== Vault search (2) ============================================
  {
    id: "search-classifier-type-filter",
    question: "Does filtering by classifier type return only documents of that type?",
    rationale:
      "Classifier-typed lookup is the LLM's main vault entry point. A leak across types would surface a payslip when the host asked for a tax return.",
    tool: "search_documents",
    async run() {
      const vaultRoot = mkdtempSync(join(tmpdir(), "penge-eval-vault-"));
      try {
        buildVault(vaultRoot, SYNTHETIC_VAULT_DOCS);
        const tool = searchDocumentsTool({ vaultRoot });
        const out = await tool.handler(
          tool.inputSchema.parse({ query: "20", type: "kontoauszug" }),
          CTX,
        );
        if (out.length === 0) {
          throw new Error("expected ≥ 1 result for type=kontoauszug");
        }
        for (const hit of out) {
          if (hit.type !== "kontoauszug") {
            throw new Error(`type filter leaked: returned ${hit.type}`);
          }
        }
      } finally {
        rmSync(vaultRoot, { recursive: true, force: true });
      }
    },
  },
  {
    id: "search-never-leaks-account-numbers",
    question:
      "Do excerpts redact IBANs, CPR numbers, and long digit runs before leaving the process?",
    rationale:
      "The vault contains scanned bank statements and tax notices. Letting raw account numbers reach the LLM host would be a category-1 leak.",
    tool: "search_documents",
    async run() {
      const vaultRoot = mkdtempSync(join(tmpdir(), "penge-eval-vault-"));
      try {
        buildVault(vaultRoot, SYNTHETIC_VAULT_DOCS);
        const tool = searchDocumentsTool({ vaultRoot });
        // Three different searches that all hit OCR passages containing
        // shapes the redactor must mask.
        const queries = ["IBAN", "CPR", "Sagsnr"];
        for (const query of queries) {
          const out = await tool.handler(tool.inputSchema.parse({ query }), CTX);
          for (const hit of out) {
            expectNoRawAccountLeak(hit.excerpt, `query=${query} hash=${hit.hash}`);
          }
        }
      } finally {
        rmSync(vaultRoot, { recursive: true, force: true });
      }
    },
  },
];

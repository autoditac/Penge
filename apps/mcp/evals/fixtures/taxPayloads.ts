/**
 * Synthetic tax-calc payloads for the golden-question harness.
 *
 * The MCP `compute_tax_year` tool delegates to a Python subprocess; we
 * mock that subprocess with these pre-canned JSON payloads. The
 * numbers are calculated from a synthetic Nordnet ETF position so the
 * goldens can assert the exact line-item totals you would expect from
 * a hand calculation.
 *
 * --- DK lagerbeskatning (year 2024) ---------------------------------
 * Synthetic Nordnet ETF position: 100 units bought at 100 DKK,
 * year-end NAV 110 DKK. Mark-to-market gain = 10 DKK × 100 = 1 000
 * DKK. Tax rate 27 % on the first 61 000 DKK of capital income ⇒
 * tax_due = 270 DKK.
 *
 * --- DK AKS (Aktiesparekonto) --------------------------------------
 * 100 units at 200 DKK → 220 DKK NAV. Gain = 2 000 DKK. AKS flat
 * rate 17 % ⇒ 340 DKK.
 *
 * --- DK PAL-skat ---------------------------------------------------
 * Pension return 100 000 DKK at PAL 15.3 % ⇒ 15 300 DKK.
 *
 * --- DK carry forward ----------------------------------------------
 * Prior-year loss of 500 DKK reduces this year's taxable capital
 * income from 1 000 to 500 DKK.
 *
 * --- DE Vorabpauschale + Teilfreistellung --------------------------
 * Fund: aktienfonds (70 % Teilfreistellung).
 * Base rate × NAV = 0.0255 × 10 000 EUR = 255 EUR Vorabpauschale.
 * Teilfreistellung 30 % taxable ⇒ taxable = 76.50 EUR.
 * 26.375 % flat ⇒ tax_due = 20.17 EUR (Soli/KiSt ignored in the
 * Penge baseline calculator).
 */

import type { ComputeTaxYearOutput } from "../../src/tools/computeTaxYear.js";

// --- DK reports ------------------------------------------------------

export const DK_LAGER_EUR: ComputeTaxYearOutput = [
  {
    year: 2024,
    jurisdiction: "DK",
    currency: "EUR",
    summary: {
      gross_capital_income: 134.05,
      taxable_capital_income: 134.05,
      loss_carry_forward: 0,
      tax_withheld_total: 0,
      prior_loss_carry_forward: 0,
    },
    line_items: [
      {
        category: "lager",
        amount: 134.05,
        source: "lager:nordnet-etf-1:2024",
      },
    ],
  },
];

export const DK_AKS_DKK: ComputeTaxYearOutput = [
  {
    year: 2024,
    jurisdiction: "DK",
    currency: "DKK",
    summary: {
      gross_capital_income: 2_000,
      taxable_capital_income: 2_000,
      loss_carry_forward: 0,
      tax_withheld_total: 0,
      prior_loss_carry_forward: 0,
    },
    line_items: [
      {
        category: "ask",
        amount: 2_000,
        source: "ask:nordnet-aks-1:2024",
      },
    ],
  },
];

export const DK_PAL_DKK: ComputeTaxYearOutput = [
  {
    year: 2024,
    jurisdiction: "DK",
    currency: "DKK",
    summary: {
      gross_capital_income: 100_000,
      taxable_capital_income: 100_000,
      loss_carry_forward: 0,
      tax_withheld_total: 15_300,
      prior_loss_carry_forward: 0,
    },
    line_items: [
      {
        category: "pal",
        amount: 100_000,
        source: "pal:pfa-pension-1:2024",
      },
      {
        category: "pal_tax_withheld",
        amount: 15_300,
        source: "pal:pfa-pension-1:2024",
      },
    ],
  },
];

// Full DK report including line items whose summed gains equal the
// `taxable_capital_income` total — used to check that the
// årsopgørelse-shaped totals match the line items.
export const DK_FULL_DKK: ComputeTaxYearOutput = [
  {
    year: 2024,
    jurisdiction: "DK",
    currency: "DKK",
    summary: {
      gross_capital_income: 3_000,
      taxable_capital_income: 3_000,
      loss_carry_forward: 0,
      tax_withheld_total: 0,
      prior_loss_carry_forward: 0,
    },
    line_items: [
      { category: "lager", amount: 1_000, source: "lager:nordnet-etf-1:2024" },
      { category: "ask", amount: 2_000, source: "ask:nordnet-aks-1:2024" },
    ],
  },
];

// Carry-forward: prior loss reduces this year's taxable_capital_income
// below the gross_capital_income.
export const DK_CARRY_DKK: ComputeTaxYearOutput = [
  {
    year: 2024,
    jurisdiction: "DK",
    currency: "DKK",
    summary: {
      gross_capital_income: 1_000,
      taxable_capital_income: 500,
      loss_carry_forward: 0,
      tax_withheld_total: 0,
      prior_loss_carry_forward: 500,
    },
    line_items: [{ category: "lager", amount: 1_000, source: "lager:nordnet-etf-1:2024" }],
  },
];

// --- DE reports ------------------------------------------------------

export const DE_VORAB_BASE_EUR: ComputeTaxYearOutput = [
  {
    year: 2024,
    jurisdiction: "DE",
    currency: "EUR",
    summary: {
      vorabpauschale_total: 255,
      taxable_total: 76.5,
      tax_due_total: 20.17,
    },
    line_items: [
      { category: "vorabpauschale", amount: 255, source: "de_vorab:DE0001234567" },
      { category: "vorab_taxable", amount: 76.5, source: "de_vorab:DE0001234567" },
      { category: "vorab_tax_due", amount: 20.17, source: "de_vorab:DE0001234567" },
    ],
  },
];

// Mixed depot with two funds: one equity (70 % TF) and one Mischfonds
// (15 % TF). All three category line items appear for each fund.
export const DE_MIXED_EUR: ComputeTaxYearOutput = [
  {
    year: 2024,
    jurisdiction: "DE",
    currency: "EUR",
    summary: {
      vorabpauschale_total: 510,
      taxable_total: 280.5,
      tax_due_total: 73.98,
    },
    line_items: [
      { category: "vorabpauschale", amount: 255, source: "de_vorab:DE0001234567" },
      { category: "vorab_taxable", amount: 76.5, source: "de_vorab:DE0001234567" },
      { category: "vorab_tax_due", amount: 20.17, source: "de_vorab:DE0001234567" },
      { category: "vorabpauschale", amount: 255, source: "de_vorab:DE0009876543" },
      { category: "vorab_taxable", amount: 204, source: "de_vorab:DE0009876543" },
      { category: "vorab_tax_due", amount: 53.81, source: "de_vorab:DE0009876543" },
    ],
  },
];

// --- Constants used by the goldens to express the invariants --------

// Synthetic Nordnet ETF position used by the DK lager golden.
export const NORDNET_LAGER_GAIN_DKK = 1_000;
export const NORDNET_LAGER_TAX_RATE = 0.27;
export const AKS_RATE = 0.17;
export const PAL_RATE = 0.153;

export const PAL_PENSION_RETURN_DKK = 100_000;
export const PAL_EXPECTED_TAX_DKK = Math.round(PAL_PENSION_RETURN_DKK * PAL_RATE);

export const VORAB_BASE_NAV_EUR = 10_000;
export const VORAB_BASE_RATE = 0.0255;
export const VORAB_TF_EQUITY = 0.3;

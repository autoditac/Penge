/**
 * Synthetic scenario-engine payloads for the golden-question harness.
 *
 * The MCP `run_scenario` tool delegates to the Python Monte-Carlo
 * scenario engine. We mock that subprocess with pre-canned summaries
 * that exhibit the invariants each golden checks:
 *
 *   - p10 ≤ p50 ≤ p90 for every year on every summary.
 *   - work_reduction shifts the median FIRE year *later* (positive
 *     shift) — i.e. FIRE happens later when you cut hours.
 *   - house_purchase keeps the median FIRE year *no earlier* than
 *     baseline (shift ≥ 0).
 *   - Same seed → byte-identical summaries.
 *
 * The numbers below are illustrative — they are not the output of a
 * real Monte-Carlo run, just a self-consistent fixture that lets the
 * harness exercise the contract.
 */

import type { RunScenarioOutput } from "../../src/tools/runScenario.js";

const BASELINE_SUMMARY = {
  p10: { "2030": 150_000, "2035": 220_000, "2040": 320_000 },
  p50: { "2030": 180_000, "2035": 280_000, "2040": 420_000 },
  p90: { "2030": 220_000, "2035": 350_000, "2040": 560_000 },
  fire_year_distribution: { "2038": 100, "2039": 200, "2040": 400, "2041": 200, "2042": 100 },
} as const;

const WORK_REDUCTION_SUMMARY = {
  p10: { "2030": 130_000, "2035": 200_000, "2040": 290_000 },
  p50: { "2030": 160_000, "2035": 250_000, "2040": 380_000 },
  p90: { "2030": 200_000, "2035": 320_000, "2040": 500_000 },
  fire_year_distribution: { "2040": 100, "2041": 200, "2042": 400, "2043": 200, "2044": 100 },
} as const;

const HOUSE_PURCHASE_SUMMARY = {
  p10: { "2030": 120_000, "2035": 190_000, "2040": 300_000 },
  p50: { "2030": 170_000, "2035": 270_000, "2040": 410_000 },
  p90: { "2030": 210_000, "2035": 340_000, "2040": 550_000 },
  fire_year_distribution: { "2038": 100, "2039": 200, "2040": 400, "2041": 200, "2042": 100 },
} as const;

export const WORK_REDUCTION_PAYLOAD: RunScenarioOutput = {
  baseline: structuredClone(BASELINE_SUMMARY),
  scenario: structuredClone(WORK_REDUCTION_SUMMARY),
  // Median FIRE year shifts from 2040 to 2042 ⇒ +2.
  deltas: { p50_value_eur: -40_000, fire_year_shift_years: 2 },
};

export const HOUSE_PURCHASE_PAYLOAD: RunScenarioOutput = {
  baseline: structuredClone(BASELINE_SUMMARY),
  scenario: structuredClone(HOUSE_PURCHASE_SUMMARY),
  // Median FIRE year unchanged at 2040 ⇒ 0.
  deltas: { p50_value_eur: -10_000, fire_year_shift_years: 0 },
};

export const BASELINE_MC_PAYLOAD: RunScenarioOutput = {
  baseline: structuredClone(BASELINE_SUMMARY),
  scenario: structuredClone(BASELINE_SUMMARY),
  deltas: { p50_value_eur: 0, fire_year_shift_years: 0 },
};

// Minimal baseline JSON loaded by the run_scenario tool so we don't
// need to read from disk. The Python subprocess is mocked anyway.
export const FAKE_BASELINE_SPEC: Record<string, unknown> = {
  cashflow: { base_year: 2024, horizon_years: 20 },
  tax: {},
  goal: { target_annual_eur: "50000" },
  return_model: { asset_returns: {}, inflation: {}, block_months: 12, seed: 42 },
  mc: { n_paths: 50, asset_weights: { equity: "1" }, initial_portfolio_eur: "200000" },
};

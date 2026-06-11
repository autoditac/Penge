/** Planning-grade asset-class targets and liquidity classification.
 *
 * These are deliberate, documented defaults for dashboard v1 (#204): the
 * household has no persisted target-weight store yet, so the drift view
 * compares against this typed constant. Editable persistence is a later
 * iteration; keeping the values here makes the assumption auditable.
 *
 * Weights refer to the EUR leg of `mart_net_worth_daily` grouped by
 * `account.kind` and must sum to 1.
 */

export const targetWeightsByKind: Readonly<Record<string, number>> = {
  checking: 0.05,
  investment: 0.45,
  pension: 0.4,
  real_estate: 0.1,
};

/** Account kinds the household can spend without breaking a pension or
 * selling property. Mirrors the planning-grade liquidity split used by the
 * simulation balance sheet (docs/sim/planning-outputs.md). */
export const liquidKinds: ReadonlySet<string> = new Set(["checking", "savings", "investment"]);

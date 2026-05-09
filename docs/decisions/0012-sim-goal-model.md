# ADR-0012 — FIRE Goal Evaluation Model

| Field       | Value                            |
|-------------|----------------------------------|
| **Status**  | Accepted                         |
| **Date**    | 2025-07-03                       |
| **Issue**   | #30                              |
| **Depends** | ADR-0011 (cashflow engine)       |

## Context and Problem Statement

The household FIRE simulation needs a way to determine whether a target
annual income can be sustained from a given retirement year onward, and if
so, in which year the portfolio and pension entitlements are first sufficient
to support that income.

The two available income sources at retirement year *T* are:

1. **Safe withdrawal (SWR)** from the liquid portfolio (Nordnet + Growney
   consolidated): `swr_rate * portfolio_value_eur`
2. **Pension entitlements** that have vested by year *T*, read from the
   cashflow projection produced by `penge.sim.cashflow.project()`

The goal model must answer three questions:

- Is the goal met within the projection horizon?
- In which year is it first met?
- What is the income surplus (or shortfall) in that year?

## Decision

Implement `penge.sim.goal` with three public symbols:

- `GoalConfig` — frozen Pydantic model parameterising the goal.
- `GoalResult` — frozen Pydantic model carrying the evaluation result.
- `evaluate(goal, projection, portfolio_by_year)` — pure function that
  scans the portfolio path and returns the first year the goal is met.

### GoalConfig parameters

| Parameter             | Default  | Meaning                                      |
|-----------------------|----------|----------------------------------------------|
| `target_annual_eur`   | required | Annual income to replace (EUR)               |
| `swr_rate`            | 0.0325   | SWR fraction applied to liquid portfolio     |
| `entities`            | ()       | Entity filter; empty = all entities          |
| `require_all_vested`  | True     | Only count fully-vested pension per entity   |

### Chosen SWR default: 3.25 %

The canonical 4 % rule (Bengen 1994) was derived for a 30-year US-only
equity/bond portfolio. The household has a 40+ year horizon, a DK/DE tax
environment, and an international portfolio. Research by Pfau, Kitces, and
ERN (Early Retirement Now) suggests 3.0–3.5 % is more appropriate for
long horizons. 3.25 % is the midpoint; the caller can override via config.

### Pension vesting semantics

`cumulative_pension_eur` in `YearlyFlow` is the aggregate of all pension
accrual rules for that entity through the given year. Since there is no
per-rule breakdown in `YearlyFlow`, `require_all_vested=True` uses an
all-or-nothing rule per entity: pension counts only if **every** pension
rule for that entity has `vesting_year <= year`.

This is the conservative choice and aligns with how the household's
pensions actually work: PFA is accessible at age 63+, Beamtenpension at
statutory retirement age. Mixing partial vesting within an entity would
require per-rule cumulative tracking (see Rejected Options).

### Tax exclusion

The `evaluate` function works on **pre-tax** income. Tax netting is the
responsibility of `penge.sim.tax_overlay` (ADR-0013, #28). The Monte-Carlo
runner (#31) will compose `project()` → `tax_overlay()` → `evaluate()`.
Goal evaluation on gross income is still useful for sensitivity analysis and
FIRE runway estimation before #28 is implemented.

## Consequences

**Positive:**

- Pure function over frozen Pydantic models → trivially composable with the
  Monte-Carlo runner without mutation risk.
- Caller supplies the portfolio path → `evaluate` is independent of how the
  portfolio is grown (deterministic accumulation, bootstrap sample, or
  user-provided historical series).
- `entities` filter and `require_all_vested` toggle make the model usable
  for sensitivity analyses (e.g., "what if only Frau's pension vests on time?").

**Negative / limitations:**

- Pre-tax income overstates net income; goal may appear met earlier than in
  reality. Acceptable until #28 lands.
- `cumulative_pension_eur` is an aggregate; per-rule vesting is approximate
  (all-or-nothing per entity, not per rule).
- SWR model ignores sequence-of-returns risk within the evaluation year;
  that is handled at the Monte-Carlo level (#31).

## Rejected Options

### Per-rule cumulative pension tracking

Track a separate running cumulative for each `PensionAccrualRule` in the
cashflow engine, and expose a `pension_by_rule` field on `YearlyFlow`.
`evaluate` could then sum only the vested rules' accruals.

**Rejected** because: (1) the household currently has exactly two pension
rules per entity (one DC, one annual_eur) with the same vesting year, so
the approximation is exact for the real use case; (2) it would require
a schema change to `YearlyFlow` (breaking `CashflowProjection`) before #28
is even implemented.

### Geometric-growth portfolio model inlined in `evaluate`

Grow the portfolio by a fixed real rate inside `evaluate` instead of
accepting a `portfolio_by_year` sequence.

**Rejected** because it couples the goal model to a specific return
assumption and makes the Monte-Carlo integration harder. The caller-supplied
path pattern is more composable.

### Decumulation model

Model SWR as actual portfolio drawdown (portfolio shrinks each year;
goal fails when portfolio reaches zero).

**Rejected** as premature. The FIRE literature consensus is that the SWR
rate already implicitly models decumulation risk over the chosen horizon.
A full decumulation model would require the Monte-Carlo runner (#31) to be
complete, which depends on #28 and #31.

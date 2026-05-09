# ADR-0015 — Scenario Engine (diffs over baseline)

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| **Status**  | Accepted                                           |
| **Date**    | 2025-07-03                                         |
| **Issue**   | #32                                                |
| **Depends** | ADR-0014 (Monte-Carlo runner), ADR-0011 (cashflow) |

## Context and Problem Statement

The Monte-Carlo runner (#31) produces a single baseline simulation.  To
answer questions like *"what happens if we buy a house in 2026?"* or *"what
if one of us drops to 80% FTE?"*, we need a way to modify the baseline
cashflow/MC configuration, re-run the simulation, and compare results
side-by-side.

Acceptance criteria from issue #32:

- Scenario API documented.
- Side-by-side comparison report (markdown + JSON).
- At least two scenarios implemented and tested: `house_purchase` and
  `work_reduction`.

## Decision

### Mutation target: `CashflowProjection`

Scenarios mutate a **pre-computed `CashflowProjection`** (not the
`CashflowConfig` source), then pass the modified projection to `run()`.

**Why projection, not config?**

- `CashflowConfig` models have no per-rule year ranges (salaries apply
  for the full horizon).  Applying a year-specific mutation (e.g. salary
  reduction from year X) is impossible by modifying config rules.
- `CashflowProjection` is a flat list of `YearlyFlow` values — easy to
  iterate and patch.
- The `run()` function already consumes a projection; passing a modified
  projection requires zero changes to the runner.

### Scenario protocol

Each scenario class implements:

```python
def apply(
    self,
    proj: CashflowProjection,
    mc_cfg: MonteCarloConfig,
) -> tuple[CashflowProjection, MonteCarloConfig]:
    ...
```

The returned objects are **new instances** (Pydantic frozen models cloned
via `model_copy`); originals are never mutated.

### `compare()` shares the return model

`compare()` passes the **same** `BootstrapReturnModel` instance to every
`run()` call.  Since the model is seeded and stateless (each call to
`sample_paths` re-seeds from the stored seed), all runs draw identical
random paths.  Differences in output are therefore caused solely by the
scenario mutation, not RNG variance.

### Implemented scenarios

#### `HousePurchaseScenario`

- Reduces `initial_portfolio_eur` by `downpayment_eur`.
- Deducts the annual mortgage payment (annuity formula) from
  `liquid_contribution_eur` of the first entity in the projection for
  years `year` through `year + term_years - 1`.
- Interest-only and zero-rate mortgages are both supported.

**Limitation**: the mortgage payment is deducted from the first entity
only (alphabetically first among all entities).  For a multi-entity
projection this is a simplification; a future enhancement could accept an
`entity` parameter.

#### `WorkReductionScenario`

- Scales `gross_salary_eur` and `pension_accrual_eur` of the named entity
  by `fte_fraction` for all years ≥ `year`.
- `liquid_contribution_eur` is left unchanged (it is an explicit savings
  budget, not derived from salary in the cashflow model).
- `cumulative_pension_eur` is recomputed in a second pass so the running
  total remains consistent with the scaled accruals.

### Output: `ScenarioComparison`

`ScenarioComparison` wraps the baseline `MonteCarloResult` and a tuple of
`ScenarioResult` (name + `MonteCarloResult`).  It provides:

- `to_json()` — JSON string for machine consumption.
- `to_markdown()` — markdown table for human consumption / documentation.

## Consequences

**Positive:**

- Zero changes to the cashflow model, tax overlay, or MC runner.
- The mutation layer is thin and easy to test.
- Scenarios are composable: `compare()` runs any number in one call.
- `ScenarioComparison` is a frozen Pydantic model — JSON-serialisable,
  auditable.

**Negative / limitations:**

- Mortgage is deducted from the first entity only.  In a two-entity
  projection the "household" entity concept is not yet modelled.
- `WorkReductionScenario` does not adjust contribution rules (the user
  must manually reduce savings budgets if desired).
- The `CashflowConfig` model has no per-rule year ranges, so scenarios
  that need year-specific behavior must operate at the projection level
  (post `project()`).  This is consistent with the Phase 2 scope.

## Rejected Options

### Mutate `CashflowConfig`

The cashflow rules have no `start_year`/`end_year` fields, so time-varying
scenarios (e.g. "reduce salary from 2028") cannot be expressed.

**Rejected** as would require extending the cashflow schema, which is a
Phase 3 concern.

### New `Scenario` protocol method on `CashflowConfig`

Scenarios could produce a modified `CashflowConfig` and call `project()`
internally.  But `SalaryRule` and `ContributionRule` lack year ranges, so
the same limitation applies.

**Rejected** for the same reason as above.

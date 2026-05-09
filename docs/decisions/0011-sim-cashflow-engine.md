# 0011 — Simulation cashflow engine: deterministic per-year projection

- **Status:** Proposed
- **Date:** 2026-05-09
- **Deciders:** @autoditac
- **Tags:** sim, cashflow, FIRE

## Context and Problem Statement

The FIRE projection pipeline (issue #27) requires a module that converts
household income and savings rules into a year-by-year table of gross salary,
liquid-portfolio contributions, and pension accruals.  This table is consumed
by the goal model (#30), the tax overlay (#28), and the Monte-Carlo runner
(#31).

The cashflow engine must be:

1. **Deterministic** — identical config produces identical output every run.
2. **Fully typed and validated** — inputs at the configuration boundary are
   checked by Pydantic; illegal combinations are rejected at construction time.
3. **EUR-normalised** — all output amounts are in EUR; DKK inputs are converted
   via a caller-supplied FX rate (sourced from the ECB FX service before
   building the config).
4. **Tax-agnostic** — gross amounts only; net salary and effective tax are
   handled in the separate tax-overlay module (#28).
5. **Cheap to run** — a single projection is O(entities × horizon_years) Decimal
   arithmetic; no I/O, no randomness.

## Decision Drivers

- The Monte-Carlo runner will call the cashflow engine thousands of times with
  different return paths; it must be pure-function / allocation-light.
- DK and DE are both first-class (ADR-0004); the engine must handle DKK and EUR
  inputs without hardcoded rates.
- Tax calculation for DK (lagerbeskatning, PAL, aktiesparekonto) and DE
  (Vorabpauschale, Teilfreistellung, Beamtenpension deductions) is complex and
  evolving — deliberately excluded to keep the cashflow engine stable.

## Considered Options

1. **Single flat function with keyword arguments** — simple but hard to validate
   or serialise.
2. **Pydantic frozen config + pure `project()` function** — explicit, auditable,
   easily serialised to YAML/JSON, validated at construction.
3. **ORM-backed projection** — would pull in DB dependency; not needed for an
   in-memory projection.

## Decision Outcome

Option 2: **Pydantic frozen config + `project()` function**.

`CashflowConfig` is a frozen Pydantic model holding typed sub-rules
(`SalaryRule`, `ContributionRule`, `PensionAccrualRule`).  `project()` returns
a frozen `CashflowProjection` with a flat tuple of `YearlyFlow` records.

### Consequences

**Good:**

- The config can be serialised to YAML/JSON and round-tripped, enabling
  scenario diffing and audit trails.
- Validation errors surface at `CashflowConfig` construction, not mid-run.
- The `project()` function is a pure function; trivially testable and cacheable.

**Bad / trade-offs:**

- `Decimal` arithmetic is 5–10× slower than `float`.  Acceptable because a
  single path is microseconds, and the Monte-Carlo runner will parallelise.
- The two-decimal-place rounding in `_compound()` introduces sub-cent
  accumulation drift over 40-year horizons; this is intentional (meaningless
  precision > silent float drift for auditable outputs).

## Modelling choices

| Concept | Model |
|---|---|
| Salary growth | CPI + real wage growth, compounded annually |
| DKK → EUR | `eur_per_dkk` from `CashflowConfig`; sourced from ECB FX service by caller |
| DC pension (PFA) | Fraction of *that year's* gross salary |
| Beamtenpension accrual | Fixed annual EUR, optionally CPI-indexed |
| Tax netting | Not in scope here — handled by `penge.sim.tax` (#28) |
| Vesting | `vesting_year` stored on `PensionAccrualRule`; consumed by goal model (#30) |

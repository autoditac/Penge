# ADR-0013 — Simulation Tax Overlay

| Field       | Value                                 |
|-------------|---------------------------------------|
| **Status**  | Accepted                              |
| **Date**    | 2025-07-03                            |
| **Issue**   | #28                                   |
| **Depends** | ADR-0011 (cashflow), ADR-0012 (goal)  |

## Context and Problem Statement

The deterministic cashflow projection (ADR-0011) and the goal evaluator
(ADR-0012) both work on **gross** income: pre-tax salary and gross pension
accruals. For a realistic FIRE simulation the household needs to be able to
switch to a **net-of-tax** projection that applies the statutory rates for
the DK and DE tax regimes.

The two regimes are materially different:

- **DK**: income tax ~42 % (topskat bracket); PAL-skat 15.3 % on pension-pot
  returns; lagerbeskatning 27 %/42 % on ABIS-list ETF gains (progressive).
- **DE**: income tax ~33 % (Splittingtarif); no annual pension-pot return
  tax for Beamtenpension during accumulation; Abgeltungsteuer 26.375 % *
  70 % (Teilfreistellung) ≈ 18.46 % on equity ETF gains.

The Phase 2 goal is an **approximation** sufficient to estimate FIRE year
to ±2–3 years. A precise tax calculation (phased income, deductions,
bracket transitions) is Phase 3.

## Decision

Implement `penge.sim.tax` with:

- `EntityTaxRegime` — frozen Pydantic model holding four effective rates.
- `DK_DEFAULT` / `DE_DEFAULT` — module-level constants with household-
  appropriate defaults (overridable via `TaxConfig`).
- `TaxConfig` — frozen Pydantic model with an `enabled` flag and an
  entity→regime mapping (satisfies AC: "rates configurable in YAML").
- `apply_tax(projection, tax_config) → CashflowProjection` — returns a
  new projection with netted salary and pension accruals.
- `net_pension_drawdown(cumulative_eur, entity, tax_config) → Decimal` —
  helper for the goal model.

### Rate fields on EntityTaxRegime

| Field | Applies to | Phase-2 scope |
|---|---|---|
| `salary_income_tax_rate` | `gross_salary_eur` in projection | ✅ applied by `apply_tax` |
| `pension_return_tax_rate` | `pension_accrual_eur` (PAL-skat) | ✅ applied by `apply_tax` |
| `pension_drawdown_tax_rate` | pension income at goal time | ✅ applied by `net_pension_drawdown` |
| `capital_gains_effective_rate` | portfolio return path | 🔲 stored; consumed by MC runner (#31) |

### Gross / net switch

`TaxConfig.enabled = False` short-circuits all netting in both `apply_tax`
and `net_pension_drawdown`, returning values unchanged. This satisfies the
acceptance criterion "switch between gross / net projection".

### apply_tax transformation

```text
net_salary  = gross_salary_eur * (1 − salary_income_tax_rate)
net_accrual = pension_accrual_eur * (1 − pension_return_tax_rate)
cumulative_pension re-accumulated from net accruals per entity
liquid_contribution_eur — unchanged (pre-configured as post-tax amount)
```

### Lagerbeskatning approximation

The DK progressive rate (27 % / 42 %) depends on the annual gain, which
is a runtime quantity in the Monte-Carlo runner. For the Phase-2 default
we use 27 % (lower bracket), valid when gains per year remain below
~61 k DKK (≈ 8 k EUR at current FX). For sensitivity analysis the caller
overrides `DK_DEFAULT.capital_gains_effective_rate` in their `TaxConfig`.

### Vorabpauschale / Teilfreistellung

The DE effective rate 18.46 % = 26.375 % × 0.7 ignores:

1. The Sparerpauschbetrag (€1 000/year) — modelled as a constant
   reduction in taxable return by the Monte-Carlo runner (#31).
2. Year-to-year Vorabpauschale carry-forward — a rounding detail not
   material at simulation precision.
3. The Basiszins fluctuating annually — using the 2024 Basiszins of
   2.29 % as representative for the projection horizon.

## Consequences

**Positive:**

- Rates are data (Pydantic models, YAML-serialisable) not magic numbers.
- `enabled=False` gives a gross baseline for comparison.
- `apply_tax` returns a new `CashflowProjection` — same type as the input;
  the goal evaluator and future Monte-Carlo runner need no code change to
  switch between gross and net.
- `capital_gains_effective_rate` is carried alongside the other rates so
  the Monte-Carlo runner can read all tax parameters from one `TaxConfig`.

**Negative / limitations:**

- Effective rates are constants per entity, not functions of income level.
  This overestimates tax at lower income levels (e.g., early in career or
  in retirement). Phase 3 will use bracket tables.
- `liquid_contribution_eur` is not adjusted (it is assumed to be a post-tax
  budget amount set by the user). If a user sets it as a fraction of gross
  salary, the net cashflow may be overstated.
- The `cumulative_pension_eur` in a net projection represents
  **accrual-net-of-return-tax** pension; the `pension_drawdown_tax_rate`
  must still be applied at the goal evaluation stage via
  `net_pension_drawdown`. The two-stage design avoids double-taxation.

## Rejected Options

### Single `net_cashflow` function that applies all tax at once

Apply income tax, return tax, and drawdown tax in a single pass when the
goal is evaluated.

**Rejected** because: salary netting and accrual netting need to happen
at projection time (to compound correctly), while drawdown tax applies only
at the moment the pension is drawn. Conflating them in one function would
either compute incorrect compounding or require storing pre-tax values
alongside net values.

### Bracket-table income tax

Look up actual Danish/German tax brackets from a table and compute marginal
tax for each year's projected income.

**Rejected for Phase 2**: requires annual bracket data maintenance, and the
income projections themselves are approximate. A bracket table would add
false precision. Marked for Phase 3 when actual deductions and credits are
modelled.

### TaxConfig as part of CashflowConfig

Embed the `TaxConfig` inside `CashflowConfig` so `project()` outputs a net
projection natively.

**Rejected** because: (a) the gross projection is independently useful
(e.g., for employer-cost analysis); (b) separating concerns makes it easier
to apply different tax configs to the same gross projection in sensitivity
scenarios; (c) PR #27 is already open and adding a breaking schema change
would require rebasing.

# DE Tax — Simulation Model

This page documents the German tax rules used by the simulation engine
(`penge.sim.tax`) and the assumptions behind the default rates.

Authoritative source: BMF (Bundesministerium der Finanzen) circulars and
EStG (Einkommensteuergesetz).  Interpretations applied in code are recorded
as ADRs.

## Income tax (salary and Beamtenpension)

The German income-tax system uses a progressive Splittingtarif for
married couples (Ehegattensplitting).  For the household's combined income,
the approximate marginal rate is **33 %**.

Default: **33 %** (`DE_DEFAULT.salary_income_tax_rate`).

The Beamtenpension (civil-servant pension) is taxed as regular income at
drawdown.  The same marginal rate applies.

Default drawdown: **33 %** (`DE_DEFAULT.pension_drawdown_tax_rate`).

## Pension return tax (accumulation phase)

The Beamtenpension is not held in a commercial pot; it accrues as a state
obligation.  There is no annual return tax during the accumulation phase.

Default: **0 %** (`DE_DEFAULT.pension_return_tax_rate`).

## Abgeltungsteuer + Teilfreistellung

Capital income from the liquid portfolio (Growney + any DE-held funds) is
subject to:

- **Abgeltungsteuer**: 25 % flat rate.
- **Solidaritätszuschlag**: 5.5 % of the tax → total 26.375 %.
- **Teilfreistellung**: 30 % of gains from equity funds are exempt
  (Investmentsteuergesetz §20 Abs. 1 for Aktien-ETFs).

Effective rate on equity ETF returns:

```text
26.375 % × (1 − 0.30) = 26.375 % × 0.70 ≈ 18.46 %
```

Default: **18.46 %** (`DE_DEFAULT.capital_gains_effective_rate`).

### Sparerpauschbetrag

Each taxpayer may deduct **€1 000/year** (2023+) from capital income.  This
is not modelled as a rate reduction in Phase 2; the Monte-Carlo runner (#31)
will apply it as a fixed annual tax-free allowance before computing tax drag
on portfolio returns.

## Vorabpauschale

For accumulating ETFs (no annual distribution), Germany applies an annual
deemed distribution (Vorabpauschale):

```text
Vorabpauschale = Basiszins × 0.7 × NAV (capped at actual fund gain)
```

Taxable Vorabpauschale (after Teilfreistellung):

```text
taxable = Vorabpauschale × 0.7
```

The Basiszins for 2024 is **2.29 %** (published by BMF).

The simulation uses the effective `capital_gains_effective_rate` as a
composite approximation of Vorabpauschale + final Abgeltungsteuer at sale.
A more precise model is Phase 3 scope.

# DK Tax — Simulation Model

This page documents the Danish tax rules used by the simulation engine
(`penge.sim.tax`) and the assumptions behind the default rates.

Authoritative source: [skat.dk](https://skat.dk). Interpretations applied
in code are recorded as ADRs.

## Income tax (salary and pension drawdown)

The Danish marginal income-tax rate for a high earner (salary > ~590 k DKK)
in 2024 is approximately **42 %** (bundskat 12.11 % + topskat 15 % +
kommuneskat ~24 % + sundhedsbidrag removed from 2019, rounded).

The simulation uses a single effective rate (`salary_income_tax_rate`) per
entity, not a bracket table.  This is a conservative approximation for the
accumulation phase.  Phase 3 will add bracket tables.

Default: **42 %** (`DK_DEFAULT.salary_income_tax_rate`).

## PAL-skat (pension return tax)

PAL-skat is a **15.3 %** annual tax on the return of assets held in Danish
pension pots (PFA, Velliv, etc.).  It is withheld automatically by the
pension provider.  In the simulation, it reduces `pension_accrual_eur` by
15.3 % each year via `pension_return_tax_rate`.

Default: **15.3 %** (`DK_DEFAULT.pension_return_tax_rate`).

## Pension drawdown tax

When pension is drawn down, it is taxed as regular income.  In retirement
the household expects a lower income → lower marginal rate.

Default: **37 %** (`DK_DEFAULT.pension_drawdown_tax_rate`).
Adjust when the expected retirement income band is known.

## Lagerbeskatning (mark-to-market, ABIS-list ETFs)

ETFs on the ABIS list (most Irish-domiciled, UCITS equity funds) are taxed
annually on unrealised gains:

| Annual gain         | Tax rate |
|---------------------|----------|
| ≤ 61 900 DKK (2024) | 27 %     |
| > 61 900 DKK        | 42 %     |

The simulation stores the effective rate in
`EntityTaxRegime.capital_gains_effective_rate`.  This rate is consumed by
the Monte-Carlo runner (#31) to scale down gross portfolio returns.

Default: **27 %** (`DK_DEFAULT.capital_gains_effective_rate`).
Override to 42 % for scenarios with large annual gains.

## Aktiesparekonto (ASK)

The ASK is a separate tax wrapper with a flat **17 %** rate on realised
gains.  Deposits are capped at ~135 k DKK (2024, annually indexed).

The ASK is not modelled separately in Phase 2.  It can be approximated by
setting `capital_gains_effective_rate = 0.17` for the ASK-held portion of
the portfolio, or by running a separate sub-simulation.

## Realisationsbeskatning (non-ABIS instruments)

Instruments not on the ABIS list (individual stocks, some bonds) are taxed
on realisation at 27 %/42 % using the average-cost method
(gennemsnitsmetoden).  Not directly modelled in Phase 2 (the household
holds ABIS ETFs primarily).

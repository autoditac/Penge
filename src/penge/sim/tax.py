"""Tax overlay — approximate statutory tax rates per regime.

Applies effective tax rates to cashflow flows produced by
:mod:`penge.sim.cashflow`, enabling a "net of tax" projection.

## Scope

This module handles **income tax** on salary and **pension taxation**
(return tax and drawdown tax).  Capital-gains / portfolio return taxation
(lagerbeskatning, Vorabpauschale) is **not** applied here — those rates
reduce the gross portfolio return and are consumed by the Monte-Carlo
runner (#31) via ``EntityTaxRegime.capital_gains_effective_rate``.

## Tax regimes modelled

### Denmark (DK)

- **Income tax on salary**: top marginal rate ~42 % above ~590 k DKK.
  Use the *effective* marginal rate for the entity's projected salary band.
- **PAL-skat**: 15.3 % on pension-pot returns (automatically withheld by
  PFA).  Applied as a drag on pension accruals in the simulation.
- **Pension drawdown**: taxed as regular income at drawdown; use the
  expected marginal rate in retirement.
- **Lagerbeskatning** (ABIS-list ETFs): 27 % below 61 k DKK gains,
  42 % above.  Effective rate depends on expected annual gain; stored in
  ``capital_gains_effective_rate`` for the Monte-Carlo runner.
- **ASK**: 17 % on realised gains within the Aktiesparekonto wrapper.

### Germany (DE)

- **Income tax on salary / pension drawdown**: married-filing-joint
  Splittingtarif; approximate marginal rate for the entity's income band.
- **Abgeltungsteuer**: 25 % + 5.5 % Solidaritätszuschlag = 26.375 %.
  After 30 % Teilfreistellung on equity funds: effective ≈ 18.46 %.
  Stored in ``capital_gains_effective_rate`` for the Monte-Carlo runner.
- **Sparerpauschbetrag**: 1 000 EUR/year (≥2023) per taxpayer — modelled
  as a lump reduction in taxable capital income (out of scope here;
  handled by the Monte-Carlo runner when it builds the return path).

## Usage

::

    from penge.sim.cashflow import project, CashflowConfig
    from penge.sim.tax import TaxConfig, DE_DEFAULT, DK_DEFAULT, apply_tax

    cfg = CashflowConfig(...)
    gross_projection = project(cfg)

    tax_config = TaxConfig(
        regimes={"rouven": DK_DEFAULT, "frau": DE_DEFAULT},
    )
    net_projection = apply_tax(gross_projection, tax_config)
    # net_projection.flows have netted salary and pension accruals

    # For goal evaluation — net pension drawdown income:
    from penge.sim.tax import net_pension_drawdown
    net_income = net_pension_drawdown(
        cumulative_pension_eur=Decimal("30000"),
        entity="rouven",
        tax_config=tax_config,
    )

See ``docs/tax/dk.md`` and ``docs/tax/de.md`` for detailed tax law notes.
See ``docs/decisions/0013-sim-tax-overlay.md`` for design rationale.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from types import MappingProxyType

import pydantic

from penge.sim.cashflow import CashflowProjection, YearlyFlow

__all__ = [
    "DE_DEFAULT",
    "DK_DEFAULT",
    "EntityTaxRegime",
    "TaxConfig",
    "apply_tax",
    "net_pension_drawdown",
]


class EntityTaxRegime(pydantic.BaseModel):
    """Effective statutory tax rates for a single entity.

    All rates are fractions in ``[0, 1)``.

    Args:
        salary_income_tax_rate: Effective marginal rate on employment
            income (salaries, wages).
        pension_return_tax_rate: Annual drag on pension-pot returns
            (DK: PAL-skat 15.3 %; DE: Riester/Rürup typically 0 during
            accumulation — set 0 if not applicable).
        pension_drawdown_tax_rate: Rate on pension income at drawdown
            (DK/DE: taxed as regular income; use expected retirement
            marginal rate).
        capital_gains_effective_rate: Effective rate on liquid portfolio
            returns after regime-specific exemptions (DK lagerbeskatning,
            DE Abgeltungsteuer after Teilfreistellung + Sparerpauschbetrag).
            **Not applied by** :func:`apply_tax`; stored here for the
            Monte-Carlo runner (#31) to scale down gross portfolio returns.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    salary_income_tax_rate: Decimal
    pension_return_tax_rate: Decimal
    pension_drawdown_tax_rate: Decimal
    capital_gains_effective_rate: Decimal

    @pydantic.field_validator(
        "salary_income_tax_rate",
        "pension_return_tax_rate",
        "pension_drawdown_tax_rate",
        "capital_gains_effective_rate",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return Decimal(str(v))

    @pydantic.model_validator(mode="after")
    def _validate_rates(self) -> EntityTaxRegime:
        for field_name in (
            "salary_income_tax_rate",
            "pension_return_tax_rate",
            "pension_drawdown_tax_rate",
            "capital_gains_effective_rate",
        ):
            rate = getattr(self, field_name)
            if not (Decimal("0") <= rate < Decimal("1")):
                raise ValueError(f"{field_name} must be in [0, 1)")
        return self


#: Default DK regime for a high-income DK resident.
#:
#: - salary_income_tax_rate 42 %: top marginal income-tax bracket (bundskat
#:   + topskat + kommuneskat ≈ 42 % effective for salary > ~590 k DKK).
#: - pension_return_tax_rate 15.3 %: PAL-skat (withheld by PFA).
#: - pension_drawdown_tax_rate 37 %: expected marginal rate in retirement
#:   (assumes somewhat lower income; adjusted when more info available).
#: - capital_gains_effective_rate 27 %: lagerbeskatning at lower rate;
#:   update to 42 % if projected annual gain exceeds 61 k DKK threshold.
DK_DEFAULT = EntityTaxRegime(
    salary_income_tax_rate=Decimal("0.42"),
    pension_return_tax_rate=Decimal("0.153"),
    pension_drawdown_tax_rate=Decimal("0.37"),
    capital_gains_effective_rate=Decimal("0.27"),
)

#: Default DE regime for a Beamtin (civil-servant) spouse in DE.
#:
#: - salary_income_tax_rate 33 %: approximate marginal Splittingtarif for
#:   combined household income in DE.
#: - pension_return_tax_rate 0 %: Beamtenpension accrues outside a
#:   tax-sheltered pot; no annual return tax during accumulation.
#: - pension_drawdown_tax_rate 33 %: pension at drawdown is taxed as income
#:   under the Ertragsanteil / Besteuerungsanteil regime.
#: - capital_gains_effective_rate 18.46 %: Abgeltungsteuer 26.375 % * 0.7
#:   (30 % Teilfreistellung for equity funds). Ignores Sparerpauschbetrag
#:   (handled by the Monte-Carlo runner).
DE_DEFAULT = EntityTaxRegime(
    salary_income_tax_rate=Decimal("0.33"),
    pension_return_tax_rate=Decimal("0"),
    pension_drawdown_tax_rate=Decimal("0.33"),
    capital_gains_effective_rate=Decimal("0.1846"),
)


class TaxConfig(pydantic.BaseModel):
    """Tax configuration for the overlay.

    Args:
        enabled: If ``False``, :func:`apply_tax` returns the projection
            unchanged (gross mode).  Useful for sensitivity analysis.
        regimes: Mapping from entity identifier to :class:`EntityTaxRegime`.
            Entities not in the mapping are passed through untaxed.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    enabled: bool = True
    regimes: Mapping[str, EntityTaxRegime] = pydantic.Field(
        default_factory=lambda: MappingProxyType({})
    )


def apply_tax(
    projection: CashflowProjection,
    tax_config: TaxConfig,
) -> CashflowProjection:
    """Return a copy of the projection with tax applied to income flows.

    When ``tax_config.enabled`` is ``False``, the original projection is
    returned unchanged.

    The following transformations are applied per entity per year:

    - ``gross_salary_eur``      → ``gross_salary_eur * (1 - salary_income_tax_rate)``
    - ``pension_accrual_eur``   → ``pension_accrual_eur * (1 - pension_return_tax_rate)``
    - ``cumulative_pension_eur`` → re-accumulated from netted accruals
    - ``liquid_contribution_eur`` → unchanged (it is a fixed saving budget,
      already modelled as a post-tax amount in the caller's config)

    Args:
        projection: A gross :class:`~penge.sim.cashflow.CashflowProjection`.
        tax_config: Rates and enabled flag.

    Returns:
        A new :class:`~penge.sim.cashflow.CashflowProjection` with netted
        amounts.  The ``config`` field is preserved unchanged; only the
        ``flows`` are modified.
    """
    if not tax_config.enabled:
        return projection

    cumulative_pension: dict[str, Decimal] = {}
    net_flows: list[YearlyFlow] = []

    for flow in projection.flows:
        regime = tax_config.regimes.get(flow.entity)
        if regime is None:
            net_flows.append(flow)
            continue

        net_salary = _apply_rate(flow.gross_salary_eur, regime.salary_income_tax_rate)
        net_accrual = _apply_rate(flow.pension_accrual_eur, regime.pension_return_tax_rate)

        cumulative_pension[flow.entity] = (
            cumulative_pension.get(flow.entity, Decimal("0")) + net_accrual
        )

        net_flows.append(
            YearlyFlow(
                year=flow.year,
                entity=flow.entity,
                gross_salary_eur=net_salary,
                liquid_contribution_eur=flow.liquid_contribution_eur,
                pension_accrual_eur=net_accrual,
                cumulative_pension_eur=cumulative_pension[flow.entity],
            )
        )

    return CashflowProjection(config=projection.config, flows=tuple(net_flows))


def net_pension_drawdown(
    cumulative_pension_eur: Decimal,
    entity: str,
    tax_config: TaxConfig,
) -> Decimal:
    """Net pension drawdown income after applying the entity's drawdown tax.

    If ``tax_config.enabled`` is ``False`` or the entity has no regime,
    the gross amount is returned unchanged.

    This helper is intended for use in goal evaluation (after calling
    :func:`apply_tax` on the projection, pass the netted
    ``cumulative_pension_eur`` to :func:`~penge.sim.goal.evaluate`; or
    call this function separately to net a raw gross value).

    Args:
        cumulative_pension_eur: Pre-tax pension entitlement (EUR).
        entity: Entity identifier.
        tax_config: Tax configuration.

    Returns:
        Net pension drawdown income in EUR, quantised to 2 decimal places.
    """
    if not tax_config.enabled:
        return cumulative_pension_eur
    regime = tax_config.regimes.get(entity)
    if regime is None:
        return cumulative_pension_eur
    return _apply_rate(cumulative_pension_eur, regime.pension_drawdown_tax_rate)


def _apply_rate(amount: Decimal, rate: Decimal) -> Decimal:
    """Return ``amount * (1 - rate)`` quantized to 2dp using ROUND_HALF_EVEN."""
    return (amount * (Decimal("1") - rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
